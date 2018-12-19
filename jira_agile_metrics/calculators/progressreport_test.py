import pytest
import pandas as pd
from datetime import datetime, date
from ..conftest import (
    FauxJIRA as JIRA,
    FauxIssue as Issue,
    FauxChange as Change,
    FauxFieldValue as Value
)

from ..querymanager import QueryManager
from ..utils import extend_dict

from .progressreport import (
    throughput_range_sampler,
    calculate_team_throughput_from_samples,
    calculate_epic_target,
    find_epics,
    update_story_counts,
    forecast_to_complete,
    Outcome,
    Team,
    Epic,
    ProgressReportCalculator
)

@pytest.fixture
def fields(custom_fields):
    return custom_fields + [  # customfield_001 = Team
        {'id': 'customfield_201',  'name': 'Outcome'},
        {'id': 'customfield_202',  'name': 'Deadline'},
        {'id': 'customfield_203',  'name': 'Min stories'},
        {'id': 'customfield_204',  'name': 'Max stories'},
        {'id': 'customfield_205',  'name': 'Epic'},
    ]

@pytest.fixture
def settings(custom_settings):
    return extend_dict(custom_settings, {
        'quantiles': [0.1, 0.3, 0.5],
        'progress_report': 'progress.html',
        'progress_report_title': 'Test progress report',
        'progress_report_epic_query_template': 'issuetype=epic AND Outcome={outcome}',
        'progress_report_story_query_template': 'issuetype=story AND Epic={epic}',
        'progress_report_epic_deadline_field': 'Deadline',
        'progress_report_epic_min_stories_field': 'Min stories',
        'progress_report_epic_max_stories_field': 'Max stories',
        'progress_report_epic_team_field': 'Team',
        'progress_report_teams': [
            {
                'name': 'Team 1',
                'min_throughput': 5,
                'max_throughput': 10,
                'throughput_samples': None,
                'throughput_samples_window': None,
                'wip': 1,
            }, {
                'name': 'Team 2',
                'min_throughput': None,
                'max_throughput': None,
                'throughput_samples': 'issuetype=feature AND resolution=Done',
                'throughput_samples_window': 6,
                'wip': 2,
            }
        ],
        'progress_report_outcomes': [
            {
                'key': 'O1',
                'name': 'Outcome one',
                'epic_query': None
            }, {
                'key': None,
                'name': 'Outcome two',
                'epic_query': 'outcome="Outcome two" AND status=in-progress'
            }
        ],
    })

@pytest.fixture
def query_manager(fields, settings):

    field_lookup = {v['name'].lower(): v['id'] for v in fields}

    def compare_value(i, clause):
        key, val = [s.strip() for s in clause.split('=')]
        ival = getattr(i.fields, field_lookup.get(key.lower(), key), None)
        ival = getattr(ival, 'value', ival)
        return val.strip('"') == ival

    def simple_ql(i, jql):
        clauses = [c.strip() for c in jql.split(' AND ') if "=" in c]
        return all([compare_value(i, c) for c in clauses])

    return QueryManager(
        jira=JIRA(fields=fields, filter=simple_ql, issues=[

            # Epics
            Issue("E-1",
                summary="Epic 1",
                issuetype=Value('Epic', 'epic'),
                status=Value('In progress', 'in-progress'),
                resolution=None,
                resolutiondate=None,
                created="2018-01-02 01:01:01",
                customfield_001="Team 1",
                customfield_201="O1",
                customfield_202='2018-03-01 00:00:00',
                customfield_203=10,
                customfield_204=15,
                changes=[]
            ),

            Issue("E-2",
                summary="Epic 2",
                issuetype=Value('Epic', 'epic'),
                status=Value('In progress', 'in-progress'),
                resolution=None,
                resolutiondate=None,
                created="2018-01-02 01:01:01",
                customfield_001="Team 1",
                customfield_201="O1",
                customfield_202='2018-03-01 00:00:00',
                customfield_203=None,
                customfield_204=None,
                changes=[]
            ),

            Issue("E-3",
                summary="Epic 3",
                issuetype=Value('Epic', 'epic'),
                status=Value('In progress', 'in-progress'),
                resolution=None,
                resolutiondate=None,
                created="2018-01-02 01:01:01",
                customfield_001="Team 2",
                customfield_201="O1",
                customfield_202=None,
                customfield_203=5,
                customfield_204=5,
                changes=[]
            ),

            Issue("E-4",
                summary="Epic 4",
                issuetype=Value('Epic', 'epic'),
                status=Value('In progress', 'in-progress'),
                resolution=None,
                resolutiondate=None,
                created="2018-01-02 01:01:01",
                customfield_001="Team 1",
                customfield_201="Outcome two",
                customfield_202=None,
                customfield_203=0,
                customfield_204=0,
                changes=[]
            ),

            Issue("E-4",
                summary="Epic 4",
                issuetype=Value('Epic', 'epic'),
                status=Value('Withdrawn', 'withdrawn'),
                resolution=None,
                resolutiondate=None,
                created="2018-01-02 01:01:01",
                customfield_001="Team 2",
                customfield_201="Outcome two",
                customfield_202=None,
                customfield_203=0,
                customfield_204=0,
                changes=[]
            ),
            

            # Stories for epic E-1
            Issue("A-1",
                summary="Just created",
                issuetype=Value("Story", "story"),
                status=Value("Backlog", "backlog"),
                resolution=None,
                resolutiondate=None,
                created="2018-01-01 01:01:01",
                customfield_205="E-1",
                changes=[],
            ),
            Issue("A-2",
                summary="Started",
                issuetype=Value("Story", "story"),
                status=Value("Next", "next"),
                resolution=None,
                resolutiondate=None,
                created="2018-01-02 01:01:01",
                customfield_205="E-1",
                changes=[
                    Change("2018-01-02 10:01:01", [("Flagged", None, "Impediment")]),
                    Change("2018-01-03 01:00:00", [("Flagged", "Impediment", "")]),  # blocked 1 day in the backlog (doesn't count towards blocked days)
                    Change("2018-01-03 01:01:01", [("status", "Backlog", "Next",)]),
                    Change("2018-01-04 10:01:01", [("Flagged", "", "Impediment")]),
                    Change("2018-01-05 08:01:01", [("Flagged", "Impediment", "")]),  # was blocked 1 day
                    Change("2018-01-08 10:01:01", [("Flagged", "", "Impediment")]),  # stays blocked until today
                ],
            ),
            Issue("A-3",
                summary="Completed",
                issuetype=Value("Story", "story"),
                status=Value("Done", "done"),
                resolution=Value("Done", "Done"),
                resolutiondate="2018-01-06 01:01:01",
                created="2018-01-03 01:01:01",
                customfield_205="E-1",
                changes=[
                    Change("2018-01-03 01:01:01", [("status", "Backlog", "Next",)]),
                    Change("2018-01-04 01:01:01", [("status", "Next", "Build",)]),
                    Change("2018-01-04 10:01:01", [("Flagged", None, "Impediment")]),  # should clear two days later when issue resolved
                    Change("2018-01-05 01:01:01", [("status", "Build", "QA",)]),
                    Change("2018-01-06 01:01:01", [("status", "QA", "Done",)]),
                ],
            ),
            Issue("A-4",
                summary="Moved back",
                issuetype=Value("Story", "story"),
                status=Value("Next", "next"),
                resolution=None,
                resolutiondate=None,
                created="2018-01-04 01:01:01",
                customfield_205="E-1",
                changes=[
                    Change("2018-01-04 01:01:01", [("status", "Backlog", "Next",)]),
                    Change("2018-01-05 01:01:01", [("status", "Next", "Build",)]),
                    Change("2018-01-06 01:01:01", [("status", "Build", "Next",)]),
                    Change("2018-01-07 01:01:01", [("Flagged", None, "Awaiting input")]),
                    Change("2018-01-10 10:01:01", [("Flagged", "Awaiting input", "")]),  # blocked 3 days
                ],
            ),

            # Stories for epic E-2
            Issue("A-5",
                summary="Just created",
                issuetype=Value("Story", "story"),
                status=Value("Backlog", "backlog"),
                resolution=None,
                resolutiondate=None,
                created="2018-01-01 01:01:01",
                customfield_205="E-2",
                changes=[],
            ),

            # No stories for epic E-3

            # Features, used to calculate team throughput
            Issue("F-1",
                summary="Just created",
                issuetype=Value("Feature", "feature"),
                status=Value("Backlog", "backlog"),
                resolution=None,
                resolutiondate=None,
                created="2018-01-01 01:01:01",
                changes=[],
            ),
            Issue("F-2",
                summary="Started",
                issuetype=Value("Feature", "feature"),
                status=Value("Next", "next"),
                resolution=None,
                resolutiondate=None,
                created="2018-01-02 01:01:01",
                changes=[
                    Change("2018-01-03 01:01:01", [("status", "Backlog", "Next",)]),
                ],
            ),
            Issue("F-3",
                summary="Completed",
                issuetype=Value("Feature", "feature"),
                status=Value("Done", "done"),
                resolution=Value("Done", "Done"),
                resolutiondate="2018-01-06 01:01:01",
                created="2018-01-03 01:01:01",
                customfield_205="E-1",
                changes=[
                    Change("2018-01-03 01:01:01", [("status", "Backlog", "Next",)]),
                    Change("2018-01-04 01:01:01", [("status", "Next", "Build",)]),
                    Change("2018-01-05 01:01:01", [("status", "Build", "QA",)]),
                    Change("2018-01-06 01:01:01", [("status", "QA", "Done",)]),
                ],
            ),
            Issue("F-4",
                summary="Also completed",
                issuetype=Value("Feature", "feature"),
                status=Value("Done", "done"),
                resolution=Value("Done", "Done"),
                resolutiondate="2018-01-06 01:01:03",
                created="2018-01-04 01:01:01",
                customfield_205="E-1",
                changes=[
                    Change("2018-01-04 01:01:01", [("status", "Backlog", "Next",)]),
                    Change("2018-01-05 01:01:01", [("status", "Next", "Build",)]),
                    Change("2018-01-05 01:01:02", [("status", "Build", "QA",)]),
                    Change("2018-01-06 01:01:03", [("status", "QA", "Done",)]),
                ],
            ),
            Issue("F-5",
                summary="Completed on a different day",
                issuetype=Value("Feature", "feature"),
                status=Value("Done", "done"),
                resolution=Value("Done", "Done"),
                resolutiondate="2018-01-08 01:01:01",
                created="2018-01-04 01:01:01",
                customfield_205="E-1",
                changes=[
                    Change("2018-01-04 01:01:01", [("status", "Backlog", "Next",)]),
                    Change("2018-01-05 01:01:01", [("status", "Next", "Build",)]),
                    Change("2018-01-05 01:01:02", [("status", "Build", "QA",)]),
                    Change("2018-01-08 01:01:03", [("status", "QA", "Done",)]),
                ],
            ),


        ]),
        settings=settings
    )

@pytest.fixture
def results():
    return {}
def test_throughput_range_sampler():
    sampler = throughput_range_sampler(5, 5)
    for i in range(10):
        assert sampler() == 5
    
    sampler = throughput_range_sampler(5, 10)
    for i in range(10):
        assert 5 <= sampler() <= 10

def test_calculate_epic_target():
    assert calculate_epic_target(Epic(
        key='E-1',
        summary='Epic 1',
        status='in-progress',
        resolution=None,
        resolution_date=None,
        min_stories=5,
        max_stories=5,
        team_name='Team 1',
        deadline=None,
        stories_raised=None
    )) == 5
    
    assert calculate_epic_target(Epic(
        key='E-1',
        summary='Epic 1',
        status='in-progress',
        resolution=None,
        resolution_date=None,
        min_stories=8,
        max_stories=5,
        team_name='Team 1',
        deadline=None,
        stories_raised=None
    )) == 8
    
    assert calculate_epic_target(Epic(
        key='E-1',
        summary='Epic 1',
        status='in-progress',
        resolution=None,
        resolution_date=None,
        min_stories=0,
        max_stories=3,
        team_name='Team 1',
        deadline=None,
        stories_raised=6
    )) <= 3

def test_find_epics(query_manager):

    outcome = Outcome("Outcome one", "O1", 'issuetype=epic AND Outcome=O1')
    
    epics = list(find_epics(
        query_manager=query_manager,
        epic_min_stories_field='customfield_203',
        epic_max_stories_field='customfield_204',
        epic_team_field='customfield_001',
        epic_deadline_field='customfield_202',
        outcome=outcome)
    )

    assert len(epics) == 3
    assert epics[0].__dict__ == {
        'key': 'E-1',
        'summary': 'Epic 1',
        'status': 'In progress',
        'resolution': None,
        'resolution_date': None,
        'team_name': 'Team 1',
        'deadline': datetime(2018, 3, 1, 0, 0),
        'min_stories': 10,
        'max_stories': 15,
        'stories_raised': None,
        'stories_in_backlog': None,
        'stories_in_progress': None,
        'stories_done': None,
        'first_story_started': None,
        'last_story_finished': None,
        'outcome': outcome,
        'team': None,
        'forecast': None,
        'story_query': None,
    }
    assert epics[1].key == 'E-2'
    assert epics[2].key == 'E-3'

def test_find_epics_minimal_fields(query_manager):

    outcome = Outcome("Outcome one", "O1", 'issuetype=epic AND Outcome=O1')

    epics = list(find_epics(
        query_manager=query_manager,
        epic_min_stories_field=None,
        epic_max_stories_field=None,
        epic_team_field=None,
        epic_deadline_field=None,
        outcome=outcome)
    )

    assert len(epics) == 3
    assert epics[0].__dict__ == {
        'key': 'E-1',
        'summary': 'Epic 1',
        'status': 'In progress',
        'resolution': None,
        'resolution_date': None,
        'team_name': None,
        'deadline': None,
        'min_stories': None,
        'max_stories': None,
        'stories_raised': None,
        'stories_in_backlog': None,
        'stories_in_progress': None,
        'stories_done': None,
        'first_story_started': None,
        'last_story_finished': None,
        'outcome': outcome,
        'team': None,
        'forecast': None,
        'story_query': None,
    }
    assert epics[1].key == 'E-2'
    assert epics[2].key == 'E-3'

def test_update_story_counts(query_manager, settings):
    
    e1 = Epic(
        key="E-1",
        summary="Epic 1",
        status="in-progress",
        resolution=None,
        resolution_date=None,
        min_stories=2,
        max_stories=5,
        team_name=None,
        deadline=None,
        story_query="issuetype=story AND epic=E-1"
    )

    update_story_counts(
        epic=e1,
        query_manager=query_manager,
        cycle=settings['cycle'],
        backlog_column=settings['backlog_column'],
        done_column=settings['done_column']
    )

    assert e1.stories_raised == 4
    assert e1.stories_in_backlog == 1
    assert e1.stories_in_progress == 2
    assert e1.stories_done == 1
    assert e1.first_story_started == date(2018, 1, 3)
    assert e1.last_story_finished == date(2018, 1, 6)
    assert e1.min_stories == 4
    assert e1.max_stories == 5

    e2 = Epic(
        key="E-2",
        summary="Epic 2",
        status="in-progress",
        resolution=None,
        resolution_date=None,
        min_stories=None,
        max_stories=None,
        team_name=None,
        deadline=None,
        story_query="issuetype=story AND epic=E-2"
    )

    update_story_counts(
        epic=e2,
        query_manager=query_manager,
        cycle=settings['cycle'],
        backlog_column=settings['backlog_column'],
        done_column=settings['done_column']
    )

    assert e2.stories_raised == 1
    assert e2.stories_in_backlog == 1
    assert e2.stories_in_progress == 0
    assert e2.stories_done == 0
    assert e2.first_story_started is None
    assert e2.last_story_finished is None
    assert e2.min_stories == 1
    assert e2.max_stories == 1

    e3 = Epic(
        key="E-3",
        summary="Epic 3",
        status="in-progress",
        resolution=None,
        resolution_date=None,
        min_stories=0,
        max_stories=0,
        team_name=None,
        deadline=None,
        story_query="issuetype=story AND epic=E-3"
    )

    update_story_counts(
        epic=e3,
        query_manager=query_manager,
        cycle=settings['cycle'],
        backlog_column=settings['backlog_column'],
        done_column=settings['done_column']
    )

    assert e3.stories_raised == 0
    assert e3.stories_in_backlog == 0
    assert e3.stories_in_progress == 0
    assert e3.stories_done == 0
    assert e3.first_story_started is None
    assert e3.last_story_finished is None
    assert e3.min_stories == 0
    assert e3.max_stories == 1

def test_calculate_team_throughput_from_samples(query_manager, settings):
    throughput = calculate_team_throughput_from_samples(
        query_manager,
        cycle=settings['cycle'],
        backlog_column=settings['backlog_column'],
        done_column=settings['done_column'],
        query='issuetype=feature',
        window=None,
        frequency='1D'
    )

    assert list(throughput.index) == [
        pd.Timestamp('2018-01-06'),
        pd.Timestamp('2018-01-07'),
        pd.Timestamp('2018-01-08'),
    ]
    assert throughput.to_dict('records') == [
        {'count': 2},
        {'count': 0},
        {'count': 1},
    ]

    throughput = calculate_team_throughput_from_samples(
        query_manager,
        cycle=settings['cycle'],
        backlog_column=settings['backlog_column'],
        done_column=settings['done_column'],
        query='issuetype=feature',
        window=2,
        frequency='1D'
    )

    assert list(throughput.index) == [
        pd.Timestamp('2018-01-07'),
        pd.Timestamp('2018-01-08'),
    ]
    assert throughput.to_dict('records') == [
        {'count': 0},
        {'count': 1},
    ]

    throughput = calculate_team_throughput_from_samples(
        query_manager,
        cycle=settings['cycle'],
        backlog_column=settings['backlog_column'],
        done_column=settings['done_column'],
        query='issuetype=feature',
        window=5,
        frequency='1D'
    )

    assert list(throughput.index) == [
        pd.Timestamp('2018-01-04'),
        pd.Timestamp('2018-01-05'),
        pd.Timestamp('2018-01-06'),
        pd.Timestamp('2018-01-07'),
        pd.Timestamp('2018-01-08'),
    ]
    assert throughput.to_dict('records') == [
        {'count': 0},
        {'count': 0},
        {'count': 2},
        {'count': 0},
        {'count': 1},
    ]

def test_forecast_to_complete_wip_1():
    
    team = Team(
        name='Team 1',
        wip=1,
        sampler=throughput_range_sampler(2, 2)  # makes tests predictable
    )

    epics = [
        Epic(
            key="E-1",
            summary="Epic 1",
            status="in-progress",
            resolution=None,
            resolution_date=None,
            min_stories=10,
            max_stories=10,
            team_name='Team 1',
            deadline=None,
            team=team,
            stories_raised=8,
            stories_in_backlog=5,
            stories_in_progress=0,
            stories_done=5,  # 10-5  = 5 left; 2/wk from sampler => 3 weeks
        ),
        Epic(
            key="E-2",
            summary="Epic 2",
            status="in-progress",
            resolution=None,
            resolution_date=None,
            min_stories=10,
            max_stories=10,
            team_name='Team 1',
            deadline=datetime(2018, 1, 20),  # <5 weeks away
            team=team,
            stories_raised=10,
            stories_in_backlog=5,
            stories_in_progress=0,
            stories_done=6,  # 10 - 6 = 4 left; 2/wk from sampler => 2 weeks
        ),
        Epic(
            key="E-3",
            summary="Epic 3",
            status="in-progress",
            resolution=None,
            resolution_date=None,
            min_stories=10,
            max_stories=10,
            team_name='Team 1',
            deadline=datetime(2018, 3, 1),  # >7 weeks away
            team=team,
            stories_raised=10,
            stories_in_backlog=5,
            stories_in_progress=0,
            stories_done=6,  # 10 - 6 = 4 left; 2/wk from sampler => 2 weeks
        )
    ]

    forecast_to_complete(team, epics, [0.5, 0.9], trials=10, now=datetime(2018, 1, 10))

    assert epics[0].forecast is not None
    assert epics[1].forecast is not None
    assert epics[2].forecast is not None

    assert epics[0].forecast.quantiles == [(0.5, 3.0), (0.9, 3.0)]  # no randomness in test, so +3 weeks
    assert epics[0].forecast.deadline_quantile is None  # no deadline set

    assert epics[1].forecast.quantiles == [(0.5, 5.0), (0.9, 5.0)]  # +2 weeks after E-1 since wip=1
    assert epics[1].forecast.deadline_quantile == 0  # deadline is before best case scenario

    assert epics[2].forecast.quantiles == [(0.5, 7.0), (0.9, 7.0)]  # +2 weeks after E-2 since wip=1
    assert epics[2].forecast.deadline_quantile == 1  # deadline is after worst case scenario

def test_forecast_to_complete_wip_2():

    # double the wip, but also double the throughput of wip=1 test
    team = Team(
        name='Team 1',
        wip=2,
        sampler=throughput_range_sampler(4, 4)  # makes tests predictable
    )

    epics = [
        Epic(
            key="E-1",
            summary="Epic 1",
            status="in-progress",
            resolution=None,
            resolution_date=None,
            min_stories=10,
            max_stories=10,
            team_name='Team 1',
            deadline=None,
            team=team,
            stories_raised=8,
            stories_in_backlog=5,
            stories_in_progress=0,
            stories_done=5,  # 10-5  = 5 left; 2/wk from sampler => 3 weeks
        ),
        Epic(
            key="E-2",
            summary="Epic 2",
            status="in-progress",
            resolution=None,
            resolution_date=None,
            min_stories=10,
            max_stories=10,
            team_name='Team 1',
            deadline=datetime(2018, 1, 20),  # <2 weeks away
            team=team,
            stories_raised=10,
            stories_in_backlog=5,
            stories_in_progress=0,
            stories_done=6,  # 10 - 6 = 4 left; 2/wk from sampler => 2 weeks
        ),
        Epic(
            key="E-3",
            summary="Epic 3",
            status="in-progress",
            resolution=None,
            resolution_date=None,
            min_stories=10,
            max_stories=10,
            team_name='Team 1',
            deadline=datetime(2018, 3, 1),  # >4 weeks away
            team=team,
            stories_raised=10,
            stories_in_backlog=5,
            stories_in_progress=0,
            stories_done=6,  # 10 - 6 = 4 left; 2/wk from sampler => 2 weeks, starting after E-2
        )
    ]

    forecast_to_complete(team, epics, [0.5, 0.9], trials=10, now=datetime(2018, 1, 10))

    assert epics[0].forecast is not None
    assert epics[1].forecast is not None
    assert epics[2].forecast is not None

    assert epics[0].forecast.quantiles == [(0.5, 3.0), (0.9, 3.0)]  # no randomness in test, so +3 weeks
    assert epics[0].forecast.deadline_quantile is None  # no deadline set

    assert epics[1].forecast.quantiles == [(0.5, 2.0), (0.9, 2.0)]  # +2 weeks in parallel with E-1 since wip=2
    assert epics[1].forecast.deadline_quantile == 0.55  # deadline is same week as best case scenario

    assert epics[2].forecast.quantiles == [(0.5, 4.0), (0.9, 4.0)]  # +2 weeks after E-2 since wip=2 and it finishes first
    assert epics[2].forecast.deadline_quantile == 1  # deadline is after worst case scenario

def test_forecast_to_complete_no_epics():
    team = Team(
        name='Team 1',
        wip=1,
        sampler=throughput_range_sampler(2, 2)  # makes tests predictable
    )

    epics = []

    forecast_to_complete(team, epics, [0.5, 0.9], trials=10, now=datetime(2018, 1, 10))

    assert len(epics) == 0

def test_forecast_to_complete_with_randomness():
    
    team = Team(
        name='Team 1',
        wip=2,
        sampler=throughput_range_sampler(4, 9)  # makes tests predictable
    )

    epics = [
        Epic(
            key="E-1",
            summary="Epic 1",
            status="in-progress",
            resolution=None,
            resolution_date=None,
            min_stories=10,
            max_stories=15,
            team_name='Team 1',
            deadline=None,
            team=team,
            stories_raised=8,
            stories_in_backlog=5,
            stories_in_progress=0,
            stories_done=5,
        ),
        Epic(
            key="E-2",
            summary="Epic 2",
            status="in-progress",
            resolution=None,
            resolution_date=None,
            min_stories=10,
            max_stories=20,
            team_name='Team 1',
            deadline=datetime(2018, 1, 20),
            team=team,
            stories_raised=10,
            stories_in_backlog=5,
            stories_in_progress=0,
            stories_done=6,
        ),
        Epic(
            key="E-3",
            summary="Epic 3",
            status="in-progress",
            resolution=None,
            resolution_date=None,
            min_stories=10,
            max_stories=10,
            team_name='Team 1',
            deadline=datetime(2018, 3, 1),
            team=team,
            stories_raised=10,
            stories_in_backlog=5,
            stories_in_progress=0,
            stories_done=6,
        )
    ]

    forecast_to_complete(team, epics, [0.5, 0.9], trials=100, now=datetime(2018, 1, 10))

    assert epics[0].forecast is not None
    assert epics[1].forecast is not None
    assert epics[2].forecast is not None

    assert [q[0] for q in epics[0].forecast.quantiles] == [0.5, 0.9]
    assert epics[0].forecast.deadline_quantile is None

    assert [q[0] for q in epics[1].forecast.quantiles] == [0.5, 0.9]
    assert epics[1].forecast.deadline_quantile > 0 and epics[1].forecast.deadline_quantile < 1

    assert [q[0] for q in epics[2].forecast.quantiles] == [0.5, 0.9]
    assert epics[2].forecast.deadline_quantile == 1  # deadline is after worst case scenario

def test_calculator(query_manager, settings, results):
    
    calculator = ProgressReportCalculator(query_manager, settings, results)

    data = calculator.run(trials=10, now=datetime(2018, 1, 10))

    # confirm it has set up the two outcomes
    assert len(data['outcomes']) == 2
    assert data['outcomes'][0].name == 'Outcome one'
    assert data['outcomes'][0].key == 'O1'
    assert data['outcomes'][1].name == 'Outcome two'
    assert data['outcomes'][1].key == 'Outcome two'

    # confirm it has found the right epics for each outcome
    assert [e.key for e in data['outcomes'][0].epics] == ['E-1', 'E-2', 'E-3']
    assert [e.key for e in data['outcomes'][1].epics] == ['E-4']

    # confirm it has mapped the right teams to the right epics
    assert [e.team.name for e in data['outcomes'][0].epics] == ['Team 1', 'Team 1', 'Team 2']
    assert [e.team.name for e in data['outcomes'][1].epics] == ['Team 1']

    # confirm it has updated stories count as per `update_story_counts()`
    assert data['outcomes'][0].epics[0].stories_raised == 4
    assert data['outcomes'][0].epics[0].stories_in_backlog == 1
    assert data['outcomes'][0].epics[0].stories_in_progress == 2
    assert data['outcomes'][0].epics[0].stories_done == 1
    assert data['outcomes'][0].epics[0].first_story_started == date(2018, 1, 3)
    assert data['outcomes'][0].epics[0].last_story_finished == date(2018, 1, 6)

    # confirm it has attempted a forecast
    assert data['outcomes'][0].epics[0].forecast is not None
    assert data['outcomes'][0].epics[0].forecast.deadline_quantile is not None
    assert [q[0] for q in data['outcomes'][0].epics[0].forecast.quantiles] == [0.1, 0.3, 0.5]

    # confirm teams
    assert len(data['teams']) == 2
    
    assert data['teams'][0].name == 'Team 1'
    assert data['teams'][0].min_throughput == 5
    assert data['teams'][0].max_throughput == 10
    assert data['teams'][0].throughput_samples is None
    assert data['teams'][0].throughput_samples_window is None

    assert data['teams'][1].name == 'Team 2'
    assert data['teams'][1].min_throughput is None
    assert data['teams'][1].max_throughput is None
    assert data['teams'][1].throughput_samples == 'issuetype=feature AND resolution=Done'
    assert data['teams'][1].throughput_samples_window == 6

    # results[ProgressReportCalculator] = data
    # calculator.write()

def test_calculator_no_outcomes(query_manager, settings, results):
    settings = extend_dict(settings, {
        'progress_report_epic_query_template': 'issuetype=epic AND Outcome="O1',
        'progress_report_outcomes': [],
    })
    
    calculator = ProgressReportCalculator(query_manager, settings, results)

    data = calculator.run(trials=10, now=datetime(2018, 1, 10))

    # confirm it has set up the two outcomes
    assert len(data['outcomes']) == 1
    assert data['outcomes'][0].name is None
    assert data['outcomes'][0].key is None

    # confirm it has found the right epics for each outcome
    assert [e.key for e in data['outcomes'][0].epics] == ['E-1', 'E-2', 'E-3']

    # confirm it has mapped the right teams to the right epics
    assert [e.team.name for e in data['outcomes'][0].epics] == ['Team 1', 'Team 1', 'Team 2']

    # confirm it has updated stories count as per `update_story_counts()`
    assert data['outcomes'][0].epics[0].stories_raised == 4
    assert data['outcomes'][0].epics[0].stories_in_backlog == 1
    assert data['outcomes'][0].epics[0].stories_in_progress == 2
    assert data['outcomes'][0].epics[0].stories_done == 1
    assert data['outcomes'][0].epics[0].first_story_started == date(2018, 1, 3)
    assert data['outcomes'][0].epics[0].last_story_finished == date(2018, 1, 6)

    # confirm it has attempted a forecast
    assert data['outcomes'][0].epics[0].forecast is not None
    assert data['outcomes'][0].epics[0].forecast.deadline_quantile is not None
    assert [q[0] for q in data['outcomes'][0].epics[0].forecast.quantiles] == [0.1, 0.3, 0.5]

    # confirm teams
    assert len(data['teams']) == 2
    
    assert data['teams'][0].name == 'Team 1'
    assert data['teams'][0].min_throughput == 5
    assert data['teams'][0].max_throughput == 10
    assert data['teams'][0].throughput_samples is None
    assert data['teams'][0].throughput_samples_window is None

    assert data['teams'][1].name == 'Team 2'
    assert data['teams'][1].min_throughput is None
    assert data['teams'][1].max_throughput is None
    assert data['teams'][1].throughput_samples == 'issuetype=feature AND resolution=Done'
    assert data['teams'][1].throughput_samples_window == 6

def test_calculator_no_fields(query_manager, settings, results):
    settings = extend_dict(settings, {
        'progress_report_epic_deadline_field': None,
        'progress_report_epic_min_stories_field': None,
        'progress_report_epic_max_stories_field': None,
        'progress_report_epic_team_field': None,
        'progress_report_teams': [
            {
                'name': 'Team 1',
                'min_throughput': 5,
                'max_throughput': 10,
                'throughput_samples': None,
                'throughput_samples_window': None,
                'wip': 1,
            }
        ],
    })

    calculator = ProgressReportCalculator(query_manager, settings, results)

    data = calculator.run(trials=10, now=datetime(2018, 1, 10))

    # confirm it has set up the two outcomes
    assert len(data['outcomes']) == 2
    assert data['outcomes'][0].name == 'Outcome one'
    assert data['outcomes'][0].key == 'O1'
    assert data['outcomes'][1].name == 'Outcome two'
    assert data['outcomes'][1].key == 'Outcome two'

    # confirm it has found the right epics for each outcome
    assert [e.key for e in data['outcomes'][0].epics] == ['E-1', 'E-2', 'E-3']
    assert [e.key for e in data['outcomes'][1].epics] == ['E-4']

    # all epics use the default team
    assert [e.team.name for e in data['outcomes'][0].epics] == ['Team 1', 'Team 1', 'Team 1']
    assert [e.team.name for e in data['outcomes'][1].epics] == ['Team 1']

    # confirm it has updated stories count as per `update_story_counts()`
    assert data['outcomes'][0].epics[0].stories_raised == 4
    assert data['outcomes'][0].epics[0].stories_in_backlog == 1
    assert data['outcomes'][0].epics[0].stories_in_progress == 2
    assert data['outcomes'][0].epics[0].stories_done == 1
    assert data['outcomes'][0].epics[0].first_story_started == date(2018, 1, 3)
    assert data['outcomes'][0].epics[0].last_story_finished == date(2018, 1, 6)

    # confirm it has attempted a forecast
    assert data['outcomes'][0].epics[0].forecast is not None
    assert data['outcomes'][0].epics[0].forecast.deadline_quantile is None
    assert [q[0] for q in data['outcomes'][0].epics[0].forecast.quantiles] == [0.1, 0.3, 0.5]

    # confirm teams
    assert len(data['teams']) == 1
    
    assert data['teams'][0].name == 'Team 1'
    assert data['teams'][0].min_throughput == 5
    assert data['teams'][0].max_throughput == 10
    assert data['teams'][0].throughput_samples is None
    assert data['teams'][0].throughput_samples_window is None
