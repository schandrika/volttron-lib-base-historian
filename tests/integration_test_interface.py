import pytest
import ast
import copy
from datetime import datetime, timedelta
import itertools
import random
import sqlite3
import sys
import re

from tzlocal import get_localzone
import gevent
import pytest
import pytz

from volttron.utils import format_timestamp
from volttron.utils.jsonrpc import RemoteError
from volttron.client.messaging import headers as headers_mod
from volttron.client.messaging import topics
from volttron.client import Agent

# Module level variables
DEVICES_ALL_TOPIC = "devices/Building/LAB/Device/all"
MICROSECOND_PRECISION = 0
table_names = dict()
historian_version = ""
connection_type = ""
query_points = {
    "oat_point": "Building/LAB/Device/OutsideAirTemperature",
    "mixed_point": "Building/LAB/Device/MixedAirTemperature",
    "damper_point": "Building/LAB/Device/DamperSignal"
}

offset = timedelta(seconds=3)
db_connection = None
identity = None


class HistorianTestInterface:


    @pytest.fixture(scope="module")
    def historian(self):
        pass

    @pytest.fixture(scope="module")
    def publish_agent(self, volttron_instance):
        agent = volttron_instance.build_agent()
        yield agent
        print("In teardown method of publish_agent")
        if isinstance(agent, Agent):
            agent.core.stop()

    @pytest.fixture(scope="module")
    def query_agent(self, volttron_instance):
        agent = volttron_instance.build_agent()
        yield agent
        print("In teardown method of query_agent")
        agent.core.stop()

    def random_uniform(self, a, b):
        """
        Creates a random uniform value for using within our tests.  This function
        will chop a float off at a specific uniform number of decimals.

        :param a: lower bound of range for return value
        :param b: upper bound of range for return value
        :return: A psuedo random uniform float.
        :type a: int
        :type b: int
        :rtype: float
        """
        format_spec = "{0:.13f}"
        return float(format_spec.format(random.uniform(a, b)))

    def publish(self, publish_agent, topic, header, message):
        if isinstance(publish_agent, Agent):
            publish_agent.vip.pubsub.publish('pubsub',
                                             topic,
                                             headers=header,
                                             message=message).get(timeout=10)
        else:
            publish_agent.publish_json(topic, header, message)

    def assert_timestamp(self, result, expected_date, expected_time):
        global MICROSECOND_PRECISION
        print("TIMESTAMP expected ", expected_time)
        print(f"MICROSECOND {MICROSECOND_PRECISION}")
        if expected_time[-6:] == "+00:00":
            expected_time = expected_time[:-6]

        if MICROSECOND_PRECISION > 0 and MICROSECOND_PRECISION < 6:
            truncate = (6 - MICROSECOND_PRECISION) * -1
            assert (result == expected_date + 'T'
                    + expected_time[:truncate] + '0' *
                    MICROSECOND_PRECISION + '+00:00')

        elif MICROSECOND_PRECISION == 6:
            assert result == expected_date + 'T' + expected_time + '+00:00'
        else:
            # mysql version < 5.6.4
            assert (result == expected_date + 'T' + expected_time[:-7] +
                    '.000000+00:00')

    @pytest.mark.historian
    def test_basic_function(self, historian, publish_agent, query_agent):
        """
        Test basic functionality of historian. Inserts three points as part
        of all topic and checks if all three got into the database
        Expected result:
        Should be able to query data based on topic name. Result should contain
        both data and metadata
        :param request: pytest request object
        :param publish_agent: instance of volttron 2.0/3.0agent used to publish
        :param query_agent: instance of fake volttron 3.0 agent used to query
        using rpc
        :param historian: instance of the historian tested
        :param clean_db_rows: fixture to clear data table
        """
        global query_points, DEVICES_ALL_TOPIC, db_connection, MICROSECOND_PRECISION
        identity, MICROSECOND_PRECISION = historian
        print(f"MICROSECOND {MICROSECOND_PRECISION}")
        # Publish fake data. The format mimics the format used by VOLTTRON drivers.
        # Make some random readings.  Randome readings are going to be
        # within the tolerance here.
        format_spec = "{0:.13f}"
        oat_reading = self.random_uniform(30, 100)
        mixed_reading = oat_reading + self.random_uniform(-5, 5)
        damper_reading = self.random_uniform(0, 100)

        float_meta = {'units': 'F', 'tz': 'UTC', 'type': 'float'}
        percent_meta = {'units': '%', 'tz': 'UTC', 'type': 'float'}

        # Create a message for all points.
        all_message = [{'OutsideAirTemperature': oat_reading,
                        'MixedAirTemperature': mixed_reading,
                        'DamperSignal': damper_reading},
                       {'OutsideAirTemperature': float_meta,
                        'MixedAirTemperature': float_meta,
                        'DamperSignal': percent_meta
                        }]

        # Create timestamp
        now = format_timestamp(datetime.utcnow())

        # now = '2015-12-02T00:00:00'
        headers = {
            headers_mod.DATE: now,
            headers_mod.TIMESTAMP: now
        }
        print("Published time in header: " + now)
        # Publish messages
        self.publish(publish_agent, DEVICES_ALL_TOPIC, headers, all_message)

        gevent.sleep(2)

        # Query the historian
        result = query_agent.vip.rpc.call(identity,
                                          'query',
                                          topic=query_points['oat_point'],
                                          count=20,
                                          order="LAST_TO_FIRST").get(timeout=100)
        print('Query Result', result)
        assert (len(result['values']) == 1)
        (now_date, now_time) = now.split("T")
        self.assert_timestamp(result['values'][0][0], now_date, now_time)
        assert (result['values'][0][1] == oat_reading)
        assert set(result['metadata'].items()) == set(float_meta.items())

        # Query the historian
        result = query_agent.vip.rpc.call(identity,
                                          'query',
                                          topic=query_points['mixed_point'],
                                          count=20,
                                          order="LAST_TO_FIRST").get(timeout=10)
        print('Query Result', result)
        assert (len(result['values']) == 1)
        (now_date, now_time) = now.split("T")
        self.assert_timestamp(result['values'][0][0], now_date, now_time)
        assert (result['values'][0][1] == mixed_reading)
        assert set(result['metadata'].items()) == set(float_meta.items())

        # Query the historian
        result = query_agent.vip.rpc.call(identity,
                                          'query',
                                          topic=query_points['damper_point'],
                                          count=20,
                                          order="LAST_TO_FIRST").get(timeout=10)
        print('Query Result', result)
        assert (len(result['values']) == 1)
        (now_date, now_time) = now.split("T")
        self.assert_timestamp(result['values'][0][0], now_date, now_time)
        assert (result['values'][0][1] == damper_reading)
        assert set(result['metadata'].items()) == set(percent_meta.items())
