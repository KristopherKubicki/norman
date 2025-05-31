from app.connectors.mqtt_connector import MQTTConnector


def test_process_incoming():
    connector = MQTTConnector(broker_url='localhost', topic='t')
    payload = {'topic': 't', 'payload': 'hello'}
    assert connector.process_incoming(payload) == payload


def test_send_message():
    connector = MQTTConnector(broker_url='localhost', topic='t')
    connector.send_message('hi')
    assert ('t', 'hi') in connector.client.published


def test_listen_and_process():
    connector = MQTTConnector(broker_url='localhost', topic='t')
    connector.receive_message = lambda: [{'topic': 't', 'payload': 'hi'}]
    assert connector.listen_and_process() == [{'topic': 't', 'payload': 'hi'}]
