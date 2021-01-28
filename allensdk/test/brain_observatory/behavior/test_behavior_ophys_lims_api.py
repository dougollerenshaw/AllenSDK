import pytest
import pandas as pd
import numpy as np
import h5py
import os
from contextlib import contextmanager

from allensdk.internal.api import OneResultExpectedError
from allensdk.brain_observatory.behavior.session_apis.data_io import (
    BehaviorOphysLimsApi)
from allensdk.brain_observatory.behavior.mtrain import ExtendedTrialSchema
from marshmallow.schema import ValidationError


@contextmanager
def does_not_raise(enter_result=None):
    """
    Context to help parametrize tests that may raise errors.
    If we start supporting only python 3.7+, switch to
    contextlib.nullcontext
    """
    yield enter_result



@pytest.mark.requires_bamboo
@pytest.mark.parametrize('ophys_experiment_id', [
    pytest.param(511458874),
])
def test_get_cell_roi_table(ophys_experiment_id):
    api = BehaviorOphysLimsApi(ophys_experiment_id)
    assert len(api.get_cell_specimen_table()) == 128


@pytest.mark.requires_bamboo
@pytest.mark.parametrize('ophys_experiment_id, compare_val', [
    pytest.param(789359614, '/allen/programs/braintv/production/visualbehavior/prod0/specimen_756577249/behavior_session_789295700/789220000.pkl'),
    pytest.param(0, None)
])
def test_get_behavior_stimulus_file(ophys_experiment_id, compare_val):

    if compare_val is None:
        expected_fail = False
        try:
            api = BehaviorOphysLimsApi(ophys_experiment_id)
            api.get_behavior_stimulus_file()
        except OneResultExpectedError:
            expected_fail = True
        assert expected_fail is True
    else:
        api = BehaviorOphysLimsApi(ophys_experiment_id)
        assert api.get_behavior_stimulus_file() == compare_val


@pytest.mark.requires_bamboo
@pytest.mark.parametrize('ophys_experiment_id', [789359614])
def test_get_extended_trials(ophys_experiment_id):

    api = BehaviorOphysLimsApi(ophys_experiment_id)
    df = api.get_extended_trials()
    ets = ExtendedTrialSchema(partial=False, many=True)
    data_list_cs = df.to_dict('records')
    data_list_cs_sc = ets.dump(data_list_cs)
    ets.load(data_list_cs_sc)

    df_fail = df.drop(['behavior_session_uuid'], axis=1)
    ets = ExtendedTrialSchema(partial=False, many=True)
    data_list_cs = df_fail.to_dict('records')
    data_list_cs_sc = ets.dump(data_list_cs)
    try:
        ets.load(data_list_cs_sc)
        raise RuntimeError('This should have failed with marshmallow.schema.ValidationError')
    except ValidationError:
        pass


@pytest.mark.requires_bamboo
@pytest.mark.parametrize('ophys_experiment_id', [860030092])
def test_get_nwb_filepath(ophys_experiment_id):

    api = BehaviorOphysLimsApi(ophys_experiment_id)
    assert api.get_nwb_filepath() == '/allen/programs/braintv/production/visualbehavior/prod0/specimen_823826986/ophys_session_859701393/ophys_experiment_860030092/behavior_ophys_session_860030092.nwb'


@pytest.mark.parametrize(
    "timestamps,plane_group,group_count,expected",
    [
        (np.ones(10), 1, 0, np.ones(10)),
        (np.ones(10), 1, 0, np.ones(10)),
        # middle
        (np.array([0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0]), 1, 3, np.ones(4)),
        # first
        (np.array([1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0]), 0, 4, np.ones(3)),
        # last
        (np.array([0, 1, 0, 1, 0, 1, 0, 1]), 1, 2, np.ones(4)),
        # only one group
        (np.ones(10), 0, 1, np.ones(10))
    ]
)
def test_process_ophys_plane_timestamps(
        timestamps, plane_group, group_count, expected):
    actual = BehaviorOphysLimsApi._process_ophys_plane_timestamps(
        timestamps, plane_group, group_count)
    np.testing.assert_array_equal(expected, actual)


@pytest.mark.parametrize(
    "plane_group, ophys_timestamps, dff_traces, expected, context",
    [
        (None, np.arange(10), np.arange(5).reshape(1, 5),
         np.arange(5), does_not_raise()),
        (None, np.arange(10), np.arange(20).reshape(1, 20),
         None, pytest.raises(RuntimeError)),
        (0, np.arange(10), np.arange(5).reshape(1, 5),
         np.arange(0, 10, 2), does_not_raise()),
        (0, np.arange(20), np.arange(5).reshape(1, 5),
         None, pytest.raises(RuntimeError))
    ],
    ids=["scientifica-truncate", "scientifica-raise", "mesoscope-good",
         "mesoscope-raise"]
)
def test_get_ophys_timestamps(monkeypatch, plane_group, ophys_timestamps,
                              dff_traces, expected, context):
    """Test the acquisition frame truncation only happens for
    non-mesoscope data (and raises error for scientifica data with
    longer trace frames than acquisition frames (ophys_timestamps))."""

    monkeypatch.setattr(BehaviorOphysLimsApi,
                        "get_behavior_session_id", lambda x: 123)
    monkeypatch.setattr(BehaviorOphysLimsApi, "_get_ids", lambda x: {})

    api = BehaviorOphysLimsApi(123)
    # Mocking any db calls
    monkeypatch.setattr(api, "get_sync_data",
                        lambda: {"ophys_frames": ophys_timestamps})
    monkeypatch.setattr(api, "get_raw_dff_data", lambda: dff_traces)
    monkeypatch.setattr(api, "get_imaging_plane_group", lambda: plane_group)
    monkeypatch.setattr(api, "get_plane_group_count", lambda: 2)
    with context:
        actual = api.get_ophys_timestamps()
        if expected is not None:
            np.testing.assert_array_equal(expected, actual)


def test_dff_trace_order(monkeypatch, tmpdir):
    """
    Test that BehaviorOphysLimsApi.get_raw_dff_data can reorder
    ROIs to align with what is in the cell_specimen_table
    """

    out_fname = os.path.join(tmpdir, 'dummy_dff_data.h5')
    rng = np.random.RandomState(1234)
    n_t = 100
    data = rng.random_sample((5, n_t))
    roi_names = np.array([5,3,4,2,1])
    with h5py.File(out_fname, 'w') as out_file:
        out_file.create_dataset('data', data=data)
        out_file.create_dataset('roi_names', data=roi_names.astype(bytes))

    monkeypatch.setattr(BehaviorOphysLimsApi,
                       'get_cell_roi_ids',
                       lambda x: np.array([1,2,3,4,5]))

    monkeypatch.setattr(BehaviorOphysLimsApi,
                        'get_dff_file',
                       lambda x: out_fname)

    api = BehaviorOphysLimsApi(123)
    dff_traces = api.get_raw_dff_data()

    # compare the returned traces with the input data
    # mapping to the order of the monkeypatched cell_roi_id list
    np.testing.assert_array_almost_equal(dff_traces[0,:], data[4,:], decimal=10)
    np.testing.assert_array_almost_equal(dff_traces[1,:], data[3,:], decimal=10)
    np.testing.assert_array_almost_equal(dff_traces[2,:], data[1,:], decimal=10)
    np.testing.assert_array_almost_equal(dff_traces[3,:], data[2,:], decimal=10)
    np.testing.assert_array_almost_equal(dff_traces[4,:], data[0,:], decimal=10)


def test_dff_trace_exceptions(monkeypatch, tmpdir):
    """
    Test that BehaviorOphysLimsApi.get_raw_dff_data() raises exceptions when
    dff trace file and cell_specimen_table contain different ROI IDs
    """

    # check that an exception is raised if dff_traces has an ROI ID
    # that cell_specimen_table does not
    out_fname = os.path.join(tmpdir, 'dummy_dff_data_for_exceptions.h5')
    rng = np.random.RandomState(1234)
    n_t = 100
    data = rng.random_sample((5, n_t))
    roi_names = np.array([5,3,4,2,1])
    with h5py.File(out_fname, 'w') as out_file:
        out_file.create_dataset('data', data=data)
        out_file.create_dataset('roi_names', data=roi_names.astype(bytes))

    monkeypatch.setattr(BehaviorOphysLimsApi,
                       'get_cell_roi_ids',
                       lambda x: np.array([1,3,4,5]))

    monkeypatch.setattr(BehaviorOphysLimsApi,
                        'get_dff_file',
                       lambda x: out_fname)

    api = BehaviorOphysLimsApi(123)
    with pytest.raises(RuntimeError):
        dff_traces = api.get_raw_dff_data()

    # check that an exception is raised if the cell_specimen_table
    # has an ROI ID that dff_traces does not
    out_fname = os.path.join(tmpdir, 'dummy_dff_data_for_exceptions2.h5')
    rng = np.random.RandomState(1234)
    n_t = 100
    data = rng.random_sample((5, n_t))
    roi_names = np.array([5,3,4,2,1])
    with h5py.File(out_fname, 'w') as out_file:
        out_file.create_dataset('data', data=data)
        out_file.create_dataset('roi_names', data=roi_names.astype(bytes))

    monkeypatch.setattr(BehaviorOphysLimsApi,
                       'get_cell_roi_ids',
                       lambda x: np.array([1,2,3,4,5,6]))

    monkeypatch.setattr(BehaviorOphysLimsApi,
                        'get_dff_file',
                       lambda x: out_fname)

    api = BehaviorOphysLimsApi(123)
    with pytest.raises(RuntimeError):
        dff_traces = api.get_raw_dff_data()
