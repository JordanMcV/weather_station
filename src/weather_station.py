import influxdb_client
import weatherhat
import time

OFFSET = -6
SENSOR = weatherhat.WeatherHat()
SENSOR.temperature_offset = OFFSET
INFLUXDB = influxdb_client.InfluxDBClient()


def run_weatherhat():
    while True:
        SENSOR.update(10)
        print(f'Temperature: {SENSOR.temperature}°C, Pressure: {SENSOR.pressure}hPa, Humidity: {SENSOR.humidity}%')
        if SENSOR.updated_wind_rain:
            print(f'Wind Speed: {SENSOR.wind_speed}m/s, Wind Direction: {SENSOR.wind_direction}')
            print(f'Rain Total: {SENSOR.rain_total}mm')
        time.sleep(15)



if __name__ == '__main__':
    run_weatherhat()
