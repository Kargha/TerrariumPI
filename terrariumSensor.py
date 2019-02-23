# -*- coding: utf-8 -*-
import terrariumLogging
logger = terrariumLogging.logging.getLogger(__name__)

import os.path
import re
from glob import iglob
from time import time
from pyownet import protocol
from hashlib import md5

from terrariumUtils import terrariumUtils, terrariumSingleton

from gevent import monkey, sleep
monkey.patch_all()

class terrariumSensorCache(terrariumSingleton):
  def __init__(self):
    self.__cache = {}
    self.__running = {}
    logger.debug('Initialized sensors cache')

  def set_sensor_data(self,sensor_hash,sensor_data,cache_timeout = 30):
    self.__cache[sensor_hash] = { 'data' : sensor_data, 'expire' : int(time()) + cache_timeout}
    logger.debug('Added new sensor to sensors cache with hash: {}. Total in cache: {}'.format(sensor_hash,len(self.__cache)))

  def get_sensor_data(self,sensor_hash):
    if sensor_hash in self.__cache and self.__cache[sensor_hash]['expire'] > int(time()):
      return self.__cache[sensor_hash]['data']

  def clear_sensor_data(self,sensor_hash):
    if sensor_hash in self.__cache:
      del(self.__cache[sensor_hash])

  def is_running(self,sensor_hash):
    if sensor_hash in self.__running:
      return True

    return False

  def set_running(self,sensor_hash):
    self.__running[sensor_hash] = True

  def clear_running(self,sensor_hash):
    del(self.__running[sensor_hash])

class terrariumSensorSource(object):
  TYPE = None
  VALID_SENSOR_TYPES = []

  def __init__(self, sensor_id, sensor_type, address, name = '', callback_indicator = None):
    self.__sensor_cache = terrariumSensorCache()
    self.__sensor_cache_key = None

    self.__current_value = None
    self.__erratic_errors = 0
    self.__last_update = 0

    self.exclude_avg = False

    self.sensor_id = sensor_id
    self.notification = True

    self.set_address(address)
    self.set_name(name)
    self.set_sensor_type(sensor_type,callback_indicator)

    self.set_alarm_min(0)
    self.set_alarm_max(0)
    self.set_limit_min(0)

    try:
      if not terrariumUtils.is_float(self.limit_max):
        self.set_limit_max(100)
    except AttributeError as ex:
      self.set_limit_max(100)

    # Default max diff: abs(limit_min-limit_max) * 25%
    self.set_max_diff(abs(self.get_limit_max() - self.get_limit_min()) / 4.0)
    logger.info('Loaded %s %s sensor \'%s\' on location %s.' % (self.get_type(),self.get_sensor_type(),self.get_name(),self.get_address()))

    self.update()

  def get_sensor_cache_key(self):
    if self.__sensor_cache_key is None:
      self.__sensor_cache_key = md5((self.get_type() + self.get_address()).encode()).hexdigest()

    return self.__sensor_cache_key

  def __within_limits(self,current_value):
    if self.__current_value is None or self.get_sensor_type() in ['uva','uvb','light'] or self.get_type() in ['ytxx-digital']:
      return True

    return abs(self.__current_value - current_value) < self.get_max_diff()

  def update(self, force = False):
    starttime = time()
    cached_data = self.__sensor_cache.get_sensor_data(self.get_sensor_cache_key())

    if (cached_data is None or force) and not self.__sensor_cache.is_running(self.get_sensor_cache_key()):
      self.__sensor_cache.set_running(self.get_sensor_cache_key())
      logger.debug('Start getting new {} sensor data from location: \'{}\''.format(self.get_sensor_type(),self.get_address()))
      new_data = self.load_data()

      if new_data is not None:
        self.__sensor_cache.set_sensor_data(self.get_sensor_cache_key(),new_data,terrariumSensor.UPDATE_TIMEOUT)
        cached_data = new_data

      self.__sensor_cache.clear_running(self.get_sensor_cache_key())

    current = None if cached_data is None or self.get_sensor_type() not in cached_data else cached_data[self.get_sensor_type()]
    if current is None or not (self.get_limit_min() <= current <= self.get_limit_max()):
      # Invalid current value.... log and ingore
      self.__sensor_cache.clear_sensor_data(self.get_sensor_cache_key())
      logger.warning('Measured value %s%s from %s sensor \'%s\' is outside valid range %.2f%s - %.2f%s in %.5f seconds.' % (current,
                                                                                                                            self.get_indicator(),
                                                                                                                            self.get_type(),
                                                                                                                            self.get_name(),
                                                                                                                            self.get_limit_min(),
                                                                                                                            self.get_indicator(),
                                                                                                                            self.get_limit_max(),
                                                                                                                            self.get_indicator(),
                                                                                                                            time()-starttime))

    elif not self.__within_limits(current):
      self.__erratic_errors += 1
      logger.warning('Measured value %s%s from %s sensor \'%s\' is erratic compared to previous value %s%s in %.5f seconds.' % (current,
                                                                                                                                self.get_indicator(),
                                                                                                                                self.get_type(),
                                                                                                                                self.get_name(),
                                                                                                                                self.__current_value,
                                                                                                                                self.get_indicator(),
                                                                                                                                time()-starttime))
      if self.__erratic_errors >= 5:
        logger.warning('After %s erratic measurements is the current value %s%s is promoted to a valid value for %s sensor \'%s\' in %.5f seconds.' %
                                                                                                                                   (self.__erratic_errors,
                                                                                                                                    current,
                                                                                                                                    self.get_indicator(),
                                                                                                                                    self.get_type(),
                                                                                                                                    self.get_name(),
                                                                                                                                    time()-starttime))
        # After 5 times, use the current value as the new truth
        self.__erratic_errors = 0
        self.__current_value = current
        self.__last_update = int(starttime)

      else:
        self.__sensor_cache.clear_sensor_data(self.get_sensor_cache_key())

    else:
      self.__erratic_errors = 0

      self.__last_update = int(starttime)
      logger.info('Updated %s sensor \'%s\' from %.2f%s to %.2f%s in %.5f seconds' % (self.get_type(),
                                                                                      self.get_name(),
                                                                                      0 if self.__current_value is None else self.__current_value,
                                                                                      self.get_indicator(),
                                                                                      current,
                                                                                      self.get_indicator(),
                                                                                      time()-starttime))
      self.__current_value = current

  def get_data(self):
    data = {'id' : self.get_id(),
            'hardwaretype' : self.get_type(),
            'address' : self.get_address(),
            'type' : self.get_sensor_type(),
            'indicator' : self.get_indicator(),
            'name' : self.get_name(),
            'current' : self.get_current(),
            'alarm_min' : self.get_alarm_min(),
            'alarm_max' : self.get_alarm_max(),
            'limit_min' : self.get_limit_min(),
            'limit_max' : self.get_limit_max(),
            'max_diff' : self.get_max_diff(),
            'alarm' : self.get_alarm(),
            'error' : not self.is_active(),
            'exclude_avg' : self.get_exclude_avg()
            }

    return data

  def get_type(self):
    return self.TYPE

  def get_last_update(self):
    return self.__last_update

  def load_data(self):
    return None

  def get_id(self):
    if self.sensor_id in [None,'None','']:
      self.sensor_id = md5((self.get_type() + self.get_address() + self.get_sensor_type()).encode()).hexdigest()

    return self.sensor_id

  def set_sensor_type(self,sensor_type,indicator):
    if sensor_type in terrariumSensor.valid_sensor_types():
      self.sensor_type = sensor_type
      self.__indicator = indicator

  def get_sensor_type(self):
    return self.sensor_type

  def set_address(self,address):
    self.sensor_address = address

  def get_address(self):
    return self.sensor_address

  def set_name(self,name):
    self.name = str(name)

  def get_name(self):
    return self.name

  def get_alarm_min(self):
    return self.alarm_min

  def set_alarm_min(self,limit):
    self.alarm_min = float(limit)

  def get_alarm_max(self):
    return self.alarm_max

  def set_alarm_max(self,limit):
    self.alarm_max = float(limit)

  def get_limit_min(self):
    return self.limit_min

  def set_limit_min(self,limit):
    self.limit_min = float(limit)

  def get_limit_max(self):
    return self.limit_max

  def set_limit_max(self,limit):
    self.limit_max = float(limit)

  def set_max_diff(self,value):
    self.max_diff = float(value)

  def get_max_diff(self):
    return self.max_diff

  def set_exclude_avg(self,value):
    self.exclude_avg = terrariumUtils.is_true(value)

  def get_exclude_avg(self):
    return self.exclude_avg

  def get_indicator(self):
    # Use a callback from terrariumEngine for 'realtime' updates
    return self.__indicator(self.get_sensor_type())

  def get_current(self, force = False):
    if self.__current_value is None:
      return None

    indicator = self.get_indicator().lower()
    current = self.__current_value

    if 'f' == indicator:
      current = terrariumUtils.to_fahrenheit(current)
    elif 'k' == indicator:
      current = terrariumUtils.to_kelvin(current)
    elif 'inch' == indicator:
      current = terrariumUtils.to_inches(current)
    elif 'usgall' == indicator:
      current = terrariumUtils.to_us_gallons(current)
    elif 'ukgall' == indicator:
      current = terrariumUtils.to_uk_gallons(current)

    return float(current)

  def get_alarm(self):
    if self.get_current() is None:
      return False

    return not self.get_alarm_min() <= self.get_current() <= self.get_alarm_max()

  def is_active(self):
    return int(time()) - self.get_last_update() < terrariumSensor.ERROR_TIMEOUT

  def notification_enabled(self):
    return self.notification == True

  def start(self):
    logger.info('Start up sensor %s at location %s' % (self.get_name(), self.get_address()))
    return self

  def stop(self):
    logger.info('Cleaned up sensor %s at location %s' % (self.get_name(), self.get_address()))

class terrariumRemoteSensor(terrariumSensorSource):
  TYPE = 'remote'
  VALID_SENSOR_TYPES = []

  def load_data(self):
    data = terrariumUtils.get_remote_data(self.get_address())
    if data is None:
      return None

    return { self.get_sensor_type() : data}

class terrarium1WSensor(terrariumSensorSource):
  TYPE = 'w1'
  VALID_SENSOR_TYPES = ['temperature']

  W1_BASE_PATH = '/sys/bus/w1/devices/'
  W1_TEMP_REGEX = re.compile(r'(?P<type>t|f)=(?P<value>[0-9\-]+)',re.IGNORECASE)

  def set_address(self,address):
    self.sensor_address = address if os.path.isfile(os.path.join(terrarium1WSensor.W1_BASE_PATH,address,'w1_slave')) else None

  def load_data(self):
    data = None
    if self.get_address() is not None:
      with open(os.path.join(terrarium1WSensor.W1_BASE_PATH,self.get_address(),'w1_slave'), 'r') as w1data:
        data = w1data.read()
        w1data = terrarium1WSensor.W1_TEMP_REGEX.search(data)
        if w1data:
          # Found data
          data = float(w1data.group('value')) / 1000.0

    if data is None:
      return None

    return { self.get_sensor_type() : data}

  @staticmethod
  def scan_sensors(callback = None):
    # Scanning w1 system bus
    for address in iglob(terrarium1WSensor.W1_BASE_PATH + '[1-9][0-9]-*'):
      if not os.path.isfile(address + '/w1_slave'):
        break

      data = ''
      with open(address + '/w1_slave', 'r') as w1data:
        data = w1data.read()

      w1data = terrarium1WSensor.W1_TEMP_REGEX.search(data)
      if w1data:
        # Found valid data
        yield terrarium1WSensor(None,
                                'temperature' if 't' == w1data.group('type') else 'humidity',
                                os.path.basename(address),
                                callback_indicator = callback)


class terrariumOWFSSensor(terrariumSensorSource):
  TYPE = 'owfs'
  VALID_SENSOR_TYPES = ['temperature','humidity']

  def __init__(self, sensor_id, sensor_type, address, name = '', callback_indicator = None):
    self.__host = 'localhost'
    self.__port = 4304
    super(terrariumOWFSSensor,self).__init__(sensor_id, sensor_type, address, name, callback_indicator)

  def load_data(self):
    data = None
    if self.__port > 0:
      data = {}
      try:
        proxy = protocol.proxy(self.__host, self.__port)
        try:
          data['temperature'] = float(proxy.read('/{}/temperature'.format(self.get_address())))
        except protocol.OwnetError:
          pass

        try:
          data['humidity'] = float(proxy.read('/{}/humidity'.format(self.get_address())))
        except protocol.OwnetError:
          pass

      except Exception as ex:
        logger.warning('OWFS file system is not actve / installed on this device!')

    if data is None:
      return None

    return data

  @staticmethod
  def scan_sensors(callback=None):
    try:
      proxy = protocol.proxy('localhost', 4304)
      for sensor in proxy.dir(slash=False, bus=False):
        stype = proxy.read(sensor + '/type').decode()
        address = proxy.read(sensor + '/address').decode()
        try:
          temp = float(proxy.read(sensor + '/temperature'))
          yield terrariumOWFSSensor(None,
                                    'temperature',
                                    address,
                                    callback_indicator = callback)

        except protocol.OwnetError:
          pass

        try:
          humidity = float(proxy.read(sensor + '/humidity'))
          yield terrariumOWFSSensor(None,
                                    'humidity',
                                    address,
                                    callback_indicator = callback)

        except protocol.OwnetError:
          pass

    except Exception as ex:
      logger.warning('OWFS file system is not actve / installed on this device! If this is not correct, try \'i2cdetect -y 1\' to see if device is connected.')


from terrariumAnalogSensor import terrariumSKUSEN0161Sensor
from terrariumBluetoothSensor import terrariumMiFloraSensor
from terrariumGPIOSensor import terrariumYTXXSensorDigital, terrariumDHT11Sensor, terrariumDHT22Sensor, terrariumAM2302Sensor, terrariumHCSR04Sensor
from terrariumI2CSensor import terrariumSHT2XSensor, terrariumHTU21DSensor, terrariumSi7021Sensor, terrariumBME280Sensor, terrariumChirpSensor, terrariumVEML6075Sensor, terrariumSHT3XSensor

# Not sure if this is needed here again....?
monkey.patch_all()

# terrariumSensor
class terrariumSensorTypeException(TypeError):
  '''There is a problem with loading a hardware sensor. Invalid hardware type.'''

  def __init__(self, message, *args):
    self.message = message
    super(terrariumPowerSwitchTypeException, self).__init__(message, *args)


# Factory class
class terrariumSensor(object):
  UPDATE_TIMEOUT = 29
  ERROR_TIMEOUT = 10 * 60 # 10 minutes

  SENSORS = [terrariumRemoteSensor,
             terrarium1WSensor,
             terrariumOWFSSensor,
             terrariumMiFloraSensor,
             terrariumSKUSEN0161Sensor,
             terrariumDHT11Sensor,
             terrariumDHT22Sensor,
             terrariumAM2302Sensor,
             terrariumYTXXSensorDigital,
             terrariumHCSR04Sensor,
             terrariumSHT2XSensor,
             terrariumHTU21DSensor,
             terrariumSi7021Sensor,
             terrariumBME280Sensor,
             terrariumVEML6075Sensor,
             terrariumChirpSensor,
             terrariumSHT3XSensor]

  def __new__(self, sensor_id, hardware_type, sensor_type, address, name = '', callback_indicator = None):
    for sensor in terrariumSensor.SENSORS:
      if hardware_type == sensor.TYPE:
        return sensor(sensor_id, sensor_type, address, name, callback_indicator)

    raise terrariumSensorTypeException('Power switch of type \'{}\' is unknown. We cannot controll this sensor.'.format(hardware_type))

  @staticmethod
  def valid_hardware_types2():
    data = {}
    for sensor in terrariumSensor.SENSORS:
      data[sensor.TYPE] = sensor.VALID_SENSOR_TYPES

    return data

  @staticmethod
  def valid_hardware_types():
    data = {}
    for sensor in terrariumSensor.SENSORS:
      data[sensor.TYPE] = sensor.TYPE

    return data

  @staticmethod
  def valid_sensor_types():
    data = {}
    for sensor in terrariumSensor.SENSORS:
      sensor_types = sensor.VALID_SENSOR_TYPES
      for sensor_type in sensor_types:
        data[sensor_type] = sensor_type

    # CO2 and volume is only through remote
    data['co2']    = 'co2'
    data['volume'] = 'volume'
    return data

  @staticmethod
  def scan_sensors(callback=None):
    for sensor_device in terrariumSensor.SENSORS:
      try:
        for sensor in sensor_device.scan_sensors(callback):
          yield sensor
      except AttributeError as ex:
        logger.debug('Device \'{}\' does not support hardware scanning'.format(sensor_device.TYPE))
