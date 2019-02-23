# -*- coding: utf-8 -*-
import terrariumLogging
logger = terrariumLogging.logging.getLogger(__name__)

from struct import unpack
from bluepy.btle import Scanner, Peripheral

from terrariumSensor import terrariumSensorSource, terrariumSensorCache

from gevent import monkey
monkey.patch_all()

class terrariumMiFloraSensor(terrariumSensorSource):
  TYPE = 'miflora'
  VALID_SENSOR_TYPES = ['temperature','light','moisture','fertility']

  __SCANTIME = 5
  __MIN_DB = -90
  __MIFLORA_FIRMWARE_AND_BATTERY = 56
  __MIFLORA_REALTIME_DATA_TRIGGER = 51
  __MIFLORA_GET_DATA = 53

  def __init__(self, sensor_id, sensor_type, address, name = '', callback_indicator = None):
    self.__firmware = None
    self.__battery = None
    self.__sensor_cache = terrariumSensorCache()

    if sensor_type in ['light','fertility']:
      self.set_limit_max(1000)

    super(terrariumMiFloraSensor,self).__init__(sensor_id, sensor_type, address, name, callback_indicator)

  def load_data(self):
    data = None

    if self.get_address() is not None:

      try:
        sensor = Peripheral(self.get_address())
        #Read battery and firmware version attribute
        data = sensor.readCharacteristic(terrariumMiFloraSensor.__MIFLORA_FIRMWARE_AND_BATTERY).decode('utf-8')
        data = {'battery': ord(data[0]), 'firmware' : data[2:]}

        #Enable real-time data reading
        sensor.writeCharacteristic(terrariumMiFloraSensor.__MIFLORA_REALTIME_DATA_TRIGGER, bytearray([0xa0, 0x1f]), True)
        #Read plant data
        data['temperature'], data['light'], data['moisture'], data['fertility'] = unpack('<hxIBHxxxxxx',sensor.readCharacteristic(terrariumMiFloraSensor.__MIFLORA_GET_DATA))
        # Close connection...
        sensor.disconnect()

        # Clean up
        data['temperature'] = float(data['temperature']) / 10.0
        data['light']       = float(data['light'])
        data['moisture']    = float(data['moisture'])
        data['fertility']   = float(data['fertility'])
      except Exception as ex:
        logger.warning('Error getting new data from {} sensor \'{}\'. Error message: {}'.format(self.get_type(),self.get_name(),ex))

    return data

  def get_data(self):
    data = super(terrariumMiFloraSensor,self).get_data()
    data['firmware'] = self.get_firmware()
    data['battery']  = self.get_battery()

    return data

  def get_firmware(self):
    cached_data = self.__sensor_cache.get_sensor_data(self.get_sensor_cache_key())
    if cached_data is not None and 'firmware' in cached_data:
      self.__firmware = cached_data['firmware']

    return self.__firmware

  def get_battery(self):
    cached_data = self.__sensor_cache.get_sensor_data(self.get_sensor_cache_key())
    if cached_data is not None and 'battery' in cached_data:
      self.__battery = cached_data['battery']

    return self.__battery

  @staticmethod
  def check_connection(address):
    try:
      miflora_dev = Peripheral(address)
      #Read battery and firmware version attribute
      sensor.readCharacteristic(terrariumMiFloraSensor.__MIFLORA_FIRMWARE_AND_BATTERY)
      miflora_dev.disconnect()
      return True
    except Exception as ex:
      logger.error('Error checking online state sensor at address: \'{}\'. Error: {}'.format(address,ex))

    return False

  @staticmethod
  def scan_sensors(callback = None):
    # Due to multiple bluetooth dongles, we are looping 10 times to see which devices can scan. Exit after first success
    logger.info('Scanning {} seconds for MiFlora bluetooth devices'.format(terrariumMiFloraSensor.__SCANTIME))
    ok = False
    for counter in range(10):
      try:
        for device in Scanner(counter).scan(terrariumMiFloraSensor.__SCANTIME):
          if device.rssi > terrariumMiFloraSensor.__MIN_DB and device.getValueText(9) is not None and device.getValueText(9).lower() in ['flower mate','flower care']:
            address = device.addr
            device = None
            logger.info('Found MiFlora bluetooth device at address {}'.format(address))
            ok = True
            for sensor_type in terrariumMiFloraSensor.VALID_SENSOR_TYPES:
              yield terrariumMiFloraSensor(None,
                                           sensor_type,
                                           address,
                                           callback_indicator = callback)

        # Done here...
        break

      except Exception as ex:
        pass

    if not ok:
      logger.warning('Bluetooth scanning is not enabled for normal users or there are zero Bluetooth LE devices available.... bluetooth is disabled!')
