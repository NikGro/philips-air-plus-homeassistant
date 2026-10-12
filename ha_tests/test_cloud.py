"""Cloud protocol tests use synthetic identifiers and never contact a purifier."""
import asyncio
import base64
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.philips_airplus import airmatters as api
from custom_components.philips_airplus.airmatters_mqtt import AirCloudMQTT
from custom_components.philips_airplus.airmatters_coordinator import AirCloudCoordinator
from custom_components.philips_airplus.config_flow import PhilipsAirplusConfigFlow
from custom_components.philips_airplus.fan import PhilipsAirplusFan
from custom_components.philips_airplus.sensor import PhilipsAirplusSensor, ALL_SENSOR_DESCRIPTIONS
from custom_components.philips_airplus.const import *

KEY = 'a_' + 'TestMixedAlphabet0123456789ABCDEF'[:32].ljust(32, 'Z')
DEVICE = {'device_id': 'test_purifier', 'device_info': {'name': 'Bedroom', 'type': 'Unicorn',
          'modelid': 'AC3220/10', 'is_online': True}}
STATE = {'D03102': 1, 'D0310C': 17, 'D0310D': 1, 'D03221': 1, 'D03120': 1,
         'D05207': 720, 'D0520D': 451, 'D05408': 9600, 'D0540E': 6840}
CONNECTION = api.CloudConnection('test-ats.iot.eu-central-1.amazonaws.com', '/mqtt?test=1', 'client_test', 'test_purifier')


def entry():
    return ConfigEntry(domain=DOMAIN, title='Bedroom', version=1, minor_version=1,
        unique_id='airplus_cloud:test_purifier', source='user', options={},
        discovery_keys={}, subentries_data=[], data={CONF_AUTH_MODE: AUTH_MODE_AIRPLUS_CLOUD,
        CONF_USER_ID: 'test_uid', CONF_SIGNING_KEY: KEY, CONF_DEVICE_ID: 'test_purifier',
        CONF_DEVICE_UUID: 'test_purifier', CONF_DEVICE_NAME: 'Bedroom',
        CONF_DEVICE_MODEL: 'AC3220/10', CONF_DEVICE_TYPE: 'Unicorn'})


def token(exp):
    claims = base64.urlsafe_b64encode(json.dumps({'exp': exp}).encode()).decode().rstrip('=')
    return 'header.' + claims + '.synthetic'


@pytest.mark.asyncio
async def test_token_refresh_is_single_flight_and_uses_server_clock():
    now = [1000]
    client = api.AirCloudClient(Mock(), 'test_uid', KEY, clock=lambda: now[0])
    requests = AsyncMock(side_effect=[{'meta': {'code': 0}, 'data': {'timestamp2': '123456'}},
       {'meta': {'code': 0}, 'data': {'token': token(3000)}},
       {'meta': {'code': 0}, 'data': {'timestamp2': '123457'}},
       {'meta': {'code': 0}, 'data': {'token': token(7000)}}])
    with patch.object(api, '_request', requests):
        results = await asyncio.gather(client.ensure_token(), client.ensure_token())
        assert results == [token(3000)] * 2
        assert requests.await_count == 2
        call = requests.call_args
        assert call.kwargs['body']['timestamp'] == '123456'
        assert call.kwargs['headers']['Signature'] == api.sign_request('123456', 'PHILIPS:test_uid', KEY)
        now[0] = 2500
        assert await client.ensure_token() == token(7000)
        assert requests.await_count == 4


@pytest.mark.asyncio
async def test_device_discovery_and_fresh_signed_url_per_connection():
    client = api.AirCloudClient(Mock(), 'test_uid', KEY)
    mqttinfo = {'endpoint': CONNECTION.host, 'path': CONNECTION.path,
                'client_id': CONNECTION.client_id, 'device_id': CONNECTION.device_id}
    with patch.object(client, '_authenticated', AsyncMock(side_effect=[
            [DEVICE], {'mqttinfos': [mqttinfo]}, {'mqttinfos': [{**mqttinfo, 'path': '/mqtt?test=2'}]}])) as request:
        assert await client.devices() == [DEVICE]
        first = await client.connection('test_purifier')
        second = await client.connection('test_purifier')
        assert first.path != second.path
        assert request.await_count == 3
    with patch.object(client, 'devices', AsyncMock(return_value=[DEVICE])):
        with pytest.raises(api.AirCloudAuthError):
            await client.connection('someone_else')
    with pytest.raises(api.AirCloudError):
        api.parse_connection({**mqttinfo, 'endpoint': 'unexpected.example'}, 'test_purifier')
    assert 'test=1' not in repr(CONNECTION)


@pytest.mark.asyncio
async def test_auth_rejection_renews_token_once():
    client = api.AirCloudClient(Mock(), 'test_uid', KEY)
    with patch.object(client, 'ensure_token', AsyncMock(side_effect=['old', 'fresh'])) as ensure, \
         patch.object(api, '_request', AsyncMock(side_effect=[api.AirCloudAuthError('rejected'), {'meta': {'code': 0}, 'data': [DEVICE]}])) as req:
        assert await client.devices() == [DEVICE]
        assert ensure.await_count == 2
        assert req.call_args.kwargs['headers']['Authorization'] == 'jwt fresh'


@pytest.mark.asyncio
async def test_otp_rejects_non_ascii_or_non_numeric_codes():
    otp = api.AirCloudOTP(Mock())
    for code in ['abc123', '１２３４５６', '12345', '1234567']:
        with pytest.raises(api.AirCloudAuthError):
            await otp.verify('test@example.com', code, 'verification')


@pytest.mark.asyncio
async def test_flow_finds_captured_model_and_creates_cloud_entry(tmp_path):
    hass = HomeAssistant(str(tmp_path))
    flow = PhilipsAirplusConfigFlow(); flow.hass = hass
    flow._auth_mode = AUTH_MODE_AIRPLUS_CLOUD
    flow._email = 'test@example.com'; flow._cloud_key = KEY; flow._vtoken = 'verification'
    with patch('custom_components.philips_airplus.config_flow.async_get_clientsession', return_value=Mock()), \
         patch('custom_components.philips_airplus.config_flow.AirCloudOTP.verify', AsyncMock(return_value='test_uid')), \
         patch('custom_components.philips_airplus.config_flow.AirCloudClient.devices', AsyncMock(return_value=[DEVICE])):
        result = await flow.async_step_email_otp({'otp_code': '123456'})
    assert result['type'] == 'form' and result['step_id'] == 'select_device'
    with patch.object(flow, 'async_set_unique_id', AsyncMock()), \
         patch.object(flow, '_abort_if_unique_id_configured'):
        result = await flow.async_step_select_device({'device': '0'})
    assert result['type'] == 'create_entry'
    assert result['data'][CONF_AUTH_MODE] == AUTH_MODE_AIRPLUS_CLOUD
    assert result['data'][CONF_DEVICE_MODEL] == 'AC3220/10'
    assert 'access_token' not in result['data']


@pytest.mark.asyncio
async def test_flow_retries_cloud_failure_without_reusing_consumed_otp(tmp_path):
    flow = PhilipsAirplusConfigFlow(); flow.hass = HomeAssistant(str(tmp_path))
    flow._auth_mode = AUTH_MODE_AIRPLUS_CLOUD; flow._cloud_key = KEY
    with patch('custom_components.philips_airplus.config_flow.async_get_clientsession', return_value=Mock()), \
         patch('custom_components.philips_airplus.config_flow.AirCloudOTP.verify', AsyncMock(return_value='test_uid')) as verify, \
         patch('custom_components.philips_airplus.config_flow.AirCloudClient.devices', AsyncMock(side_effect=[api.AirCloudError('offline'), [DEVICE]])):
        first = await flow.async_step_email_otp({'otp_code': '123456'})
        assert first['errors'] == {'base': 'cannot_connect'}
        second = await flow.async_step_email_otp({'otp_code': '123456'})
        assert second['step_id'] == 'select_device'
        assert verify.await_count == 1


@pytest.mark.asyncio
async def test_reported_shadow_versions_and_desired_ack_do_not_fabricate_state():
    factory = Mock(); states = []
    transport = AirCloudMQTT(CONNECTION, states.append, Mock(), client_factory=factory)
    prefix = '$aws/things/test_purifier/shadow'
    transport._handle_message(prefix+'/get/accepted', {'version': 5, 'state': {'reported': STATE}})
    transport._handle_message(prefix+'/update/accepted', {'version': 6, 'state': {'desired': {'D03102': 0}}})
    assert states[-1]['D03102'] == 1
    transport._handle_message(prefix+'/update/documents', {'current': {'version': 4, 'state': {'reported': {'D03102': 0}}}})
    assert len(states) == 1
    transport._handle_message(prefix+'/update/accepted', {'version': 7, 'state': {'reported': {'D03102': 0, 'D0310D': None}}})
    assert states[-1]['D03102'] == 0 and 'D0310D' not in states[-1]
    assert factory.call_args.kwargs['reconnect_on_failure'] is False
    await transport.close()


@pytest.mark.asyncio
async def test_mqtt_control_payload_and_reported_ack_correlation():
    client = Mock(); client.publish.return_value.rc = 0
    transport = AirCloudMQTT(CONNECTION, Mock(), Mock(), client_factory=Mock(return_value=client))
    transport.connected = True
    task = asyncio.create_task(transport.update({'D03102': 0}))
    await asyncio.sleep(0)
    args = client.publish.call_args
    sent = json.loads(args.args[1])
    assert sent['state'] == {'desired': {'D03102': 0}}
    assert args.kwargs == {'qos': 1, 'retain': False}
    transport._handle_message('$aws/things/test_purifier/shadow/update/accepted',
        {'clientToken': sent['clientToken'], 'version': 2, 'state': sent['state']})
    assert await task == {}
    for command in [{'D0310D': 0}, {'D03102': 2}, {'D0310C': 999}, {'D0520D': 720}]:
        with pytest.raises(api.AirCloudError):
            await transport.update(command)
    await transport.close()


@pytest.mark.asyncio
async def test_coordinator_fan_and_sensors_use_correct_power_and_filters(tmp_path):
    hass = HomeAssistant(str(tmp_path)); config = entry()
    with patch('custom_components.philips_airplus.airmatters_coordinator.async_get_clientsession', return_value=Mock()):
        coordinator = AirCloudCoordinator(hass, config)
    coordinator._client.devices = AsyncMock(return_value=[DEVICE])
    coordinator._client.connection = AsyncMock(return_value=CONNECTION)
    created = []
    def factory(connection, on_state, on_disconnect):
        transport = Mock(connected=True)
        transport.connect = AsyncMock(); transport.close = AsyncMock()
        async def read():
            on_state(STATE)
            return STATE
        transport.read = AsyncMock(side_effect=read); transport.update = AsyncMock()
        transport.disconnect_callback = on_disconnect
        created.append(transport); return transport
    with patch('custom_components.philips_airplus.airmatters_coordinator.AirCloudMQTT', side_effect=factory):
        coordinator.data = await coordinator._async_update_data()
        fan = PhilipsAirplusFan(coordinator, config)
        assert fan.available and fan.is_on and fan.preset_mode == 'Sleep'
        sensor = PhilipsAirplusSensor(coordinator, config, ALL_SENSOR_DESCRIPTIONS['filter_replace_percentage'])
        assert sensor.native_value == 71.2
        with patch.object(coordinator, 'async_request_refresh', AsyncMock()):
            await fan.async_turn_off()
            created[0].update.assert_awaited_once_with({'D03102': 0})
            assert fan.is_on  # desired acceptance does not assert physical state
        created[0].connected = False
        await coordinator._async_update_data()
        assert len(created) == 2 and coordinator._client.connection.await_count == 2
        created[0].close.assert_awaited_once()
    await coordinator.async_shutdown()
    assert not coordinator.is_connected
    created[1].close.assert_awaited_once()


@pytest.mark.asyncio
async def test_coordinator_auth_failure_vs_transient_retry(tmp_path):
    with patch('custom_components.philips_airplus.airmatters_coordinator.async_get_clientsession', return_value=Mock()):
        coordinator = AirCloudCoordinator(HomeAssistant(str(tmp_path)), entry())
    coordinator._client.devices = AsyncMock(side_effect=api.AirCloudAuthError('rejected'))
    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_update_data()
    assert coordinator._reconnect_task is None
    coordinator._client.devices = AsyncMock(side_effect=api.AirCloudError('temporarily offline'))
    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()
    assert coordinator._reconnect_task is not None
    await coordinator.async_shutdown()
    assert coordinator._reconnect_task is None


@pytest.mark.asyncio
async def test_signing_reference_integrity_and_mixed_alphabet():
    import hashlib
    content = f'**Secret Key**: `{KEY}`\n'.encode()
    response = Mock(status=200)
    async def chunks(size):
        yield content
    response.content.iter_chunked = chunks
    context = AsyncMock(); context.__aenter__.return_value = response
    session = Mock(); session.get.return_value = context
    with patch.object(api, 'SIGNING_SOURCE_SHA256', hashlib.sha256(content).hexdigest()):
        assert await api.load_signing_key(session) == KEY
    with pytest.raises(api.AirCloudError, match='verification'):
        await api.load_signing_key(session)


@pytest.mark.asyncio
async def test_mqtt_connect_waits_for_suback_and_disconnect_fails_pending():
    client = Mock(); client.subscribe.return_value = (0, 42); client.publish.return_value.rc = 0
    transport = AirCloudMQTT(CONNECTION, Mock(), Mock(), client_factory=Mock(return_value=client))
    task = asyncio.create_task(transport.connect())
    while not client.loop_start.called:
        await asyncio.sleep(0)
    success = SimpleNamespace(is_failure=False)
    client.on_connect(client, None, None, success, None)
    await asyncio.sleep(0)
    assert not transport.connected
    client.on_subscribe(client, None, 42, [success] * 5, None)
    await task
    assert transport.connected
    pending = asyncio.create_task(transport.read()); await asyncio.sleep(0)
    client.on_disconnect(client, None, None, None, None)
    with pytest.raises(api.AirCloudError, match='lost'):
        await pending
    assert not transport.connected
    transport._on_disconnect.assert_called_once()
    await transport.close()


@pytest.mark.asyncio
async def test_flow_reauth_cannot_switch_account(tmp_path):
    flow = PhilipsAirplusConfigFlow(); flow.hass = HomeAssistant(str(tmp_path))
    flow._auth_mode = AUTH_MODE_AIRPLUS_CLOUD; flow._cloud_key = KEY
    flow._reauth_entry = entry()
    with patch('custom_components.philips_airplus.config_flow.async_get_clientsession', return_value=Mock()), \
         patch('custom_components.philips_airplus.config_flow.AirCloudOTP.verify', AsyncMock(return_value='another_uid')):
        result = await flow.async_step_email_otp({'otp_code': '123456'})
    assert result['type'] == 'abort' and result['reason'] == 'wrong_account'


@pytest.mark.asyncio
async def test_default_setup_and_cloud_options(tmp_path):
    from custom_components.philips_airplus.config_flow import PhilipsAirplusOptionsFlowHandler
    flow = PhilipsAirplusConfigFlow(); flow.hass = HomeAssistant(str(tmp_path))
    form = await flow.async_step_user()
    assert form['data_schema']({})['auth_method'] == AUTH_MODE_AIRPLUS_CLOUD
    options = PhilipsAirplusOptionsFlowHandler(entry())
    options.hass = flow.hass
    form = await options.async_step_init()
    assert form['step_id'] == 'cloud_options'
    assert list(form['data_schema']({})) == [CONF_ENABLE_MQTT]
    result = await options.async_step_cloud_options({CONF_ENABLE_MQTT: False})
    assert result['data'] == {CONF_ENABLE_MQTT: False}


@pytest.mark.asyncio
async def test_setup_dispatches_backend_and_unloads_transport(tmp_path):
    import custom_components.philips_airplus as integration
    hass = HomeAssistant(str(tmp_path)); config = entry()
    coordinator = Mock()
    coordinator.async_config_entry_first_refresh = AsyncMock()
    coordinator.async_shutdown = AsyncMock()
    hass.config_entries = SimpleNamespace(async_forward_entry_setups=AsyncMock(),
                                          async_unload_platforms=AsyncMock(return_value=True))
    with patch.object(integration.er, 'async_get', return_value=Mock()), \
         patch.object(integration.er, 'async_entries_for_config_entry', return_value=[]), \
         patch.object(integration, '_ensure_services_registered'), \
         patch.object(integration, 'AirCloudCoordinator', return_value=coordinator) as new_backend, \
         patch.object(integration, 'PhilipsAirplusDataCoordinator') as old_backend:
        assert await integration.async_setup_entry(hass, config)
        new_backend.assert_called_once_with(hass, config)
        old_backend.assert_not_called()
        coordinator.async_config_entry_first_refresh.assert_awaited_once()
        assert await integration.async_unload_entry(hass, config)
        coordinator.async_shutdown.assert_awaited_once()
        assert config.entry_id not in hass.data[DOMAIN]


@pytest.mark.asyncio
async def test_background_disconnect_reconnects_with_fresh_metadata(tmp_path):
    with patch('custom_components.philips_airplus.airmatters_coordinator.async_get_clientsession', return_value=Mock()):
        coordinator = AirCloudCoordinator(HomeAssistant(str(tmp_path)), entry())
    coordinator._client.devices = AsyncMock(return_value=[DEVICE])
    coordinator._client.connection = AsyncMock(return_value=CONNECTION)
    received = asyncio.Event(); transports = []
    def factory(connection, on_state, on_disconnect):
        transport = Mock(connected=True, disconnect_callback=on_disconnect)
        transport.connect = AsyncMock(); transport.close = AsyncMock()
        async def read():
            on_state(STATE); received.set(); return STATE
        transport.read = AsyncMock(side_effect=read)
        transports.append(transport); return transport
    with patch('custom_components.philips_airplus.airmatters_coordinator.AirCloudMQTT', side_effect=factory):
        await coordinator._async_update_data(); received.clear()
        transports[0].connected = False; transports[0].disconnect_callback()
        assert not coordinator.is_connected
        await asyncio.wait_for(received.wait(), timeout=4)
        assert len(transports) == 2 and coordinator.is_connected
        assert coordinator._client.connection.await_count == 2
    await coordinator.async_shutdown()
