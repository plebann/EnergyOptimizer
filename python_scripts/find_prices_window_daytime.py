current_time = time.time()
today_date = time.strftime("%Y-%m-%d", time.localtime(current_time))
prices = hass.states.get('sensor.rce_prices_today').attributes['value']

price_list = [entry['rce_pln'] for entry in prices]
time_list = [entry['period'].split(' - ')[0] for entry in prices]

def create_aware_datetime_str(date_str, time_str):
    """Create an ISO datetime string with timezone offset."""
    # Parse input time
    naive_struct = time.strptime(f"{date_str} {time_str}:00", "%Y-%m-%d %H:%M:%S")
    timestamp = time.mktime(naive_struct)
    
    # Calculate timezone offset
    local_struct = time.localtime(timestamp)
    utc_struct = time.gmtime(timestamp)
    local_hour = local_struct.tm_hour
    utc_hour = utc_struct.tm_hour
    offset_h = local_hour - utc_hour
    offset_m = local_struct.tm_min - utc_struct.tm_min
    tz_offset = f"{offset_h:+03d}:{abs(offset_m):02d}"
    
    return f"{date_str}T{time_str}:00{tz_offset}"

# Find highest price window AFTER 12:00 (Daytime)
window_size = 4
max_avg_day = 0
max_idx_day = 0
for i in range(len(price_list) - window_size + 1):
    if time_list[i] < '12:00':
        continue
    if not time_list[i].endswith(':00'):
        continue
    current_avg = sum(price_list[i:i + window_size]) / window_size
    if current_avg > max_avg_day:
        max_avg_day = current_avg
        max_idx_day = i

# Set state and service call for daytime window
daytime_iso = create_aware_datetime_str(today_date, time_list[max_idx_day])
hass.states.set('sensor.highest_price_window_daytime', daytime_iso, {
    'friendly_name': 'Highest Price Window Daytime',
    'average_price': max_avg_day,
    'last_update': time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(current_time)),
    'device_class': 'timestamp'
})

hass.services.call('input_datetime', 'set_datetime', {
    'entity_id': 'input_datetime.rce_highest_window_evening',
    'datetime': daytime_iso
})

# Find highest price window BEFORE 12:00 (Morning)
window_size = 4
max_avg_morn = 0
max_idx_morn = 0
for i in range(len(price_list) - window_size + 1):
    if time_list[i] < '04:00' or time_list[i] > '12:00':
        continue
    if not time_list[i].endswith(':00'):
        continue
    current_avg = sum(price_list[i:i + window_size]) / window_size
    if current_avg > max_avg_morn:
        max_avg_morn = current_avg
        max_idx_morn = i

# Set state and service call for morning window
morning_iso = create_aware_datetime_str(today_date, time_list[max_idx_morn])
hass.states.set('sensor.highest_price_window_morning', morning_iso, {
    'friendly_name': 'Highest Price Window Morning',
    'average_price': max_avg_morn,
    'last_update': time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(current_time)),
    'device_class': 'timestamp'
})

hass.services.call('input_datetime', 'set_datetime', {
    'entity_id': 'input_datetime.rce_highest_window_morning',
    'datetime': morning_iso
})

# Find lowest price window BETWEEN 8 and 21
# calculate window size
average_usage = float(hass.states.get('sensor.load_usage_history').attributes['hourly_rate']) * 1.1
average_losses = float(hass.states.get('sensor.inverter_total_losses_history').attributes['hourly_rate']) * 1.1
pv_peek = 0.8 * float(hass.states.get('sensor.solcast_pv_forecast_peak_forecast_today').state) / 1000
capacity = 20.5
soc = int(hass.states.get('sensor.inverter_battery').state)

to_charge = 1.1 * (100 - soc) * capacity / 100

net_charging = pv_peek - average_usage - average_losses

if net_charging <= 0:
    # Battery won't charge - consumption >= generation
    window_size = 0
else:
    # Time to charge with 10% safety margin
    hours_to_charge = to_charge / net_charging * 1.1
    window_size = int(hours_to_charge * 4) + 1

if window_size > 30:
    window_size = 4

logger.info(f'Using window size={window_size}, pv_peek={pv_peek}, to_charge={to_charge}, average_usage={average_usage}')

min_avg_day = float('inf')
min_idx_day = 0

if window_size > 0:
    for i in range(len(price_list) - window_size + 1):
        if time_list[i] < '08:00' or time_list[i] > '21:00':
            continue
        current_avg = sum(price_list[i:i + window_size]) / window_size
        if current_avg < min_avg_day:
            min_avg_day = current_avg
            min_idx_day = i

    min_time_str = create_aware_datetime_str(today_date, time_list[min_idx_day])
else:
    min_time_str = hass.states.get('sensor.solcast_pv_forecast_peak_time_today').state


hass.states.set('sensor.lowest_price_window_daytime', min_time_str, {
    'friendly_name': "Lowest price window daytime",
    'average_price': round(min_avg_day, 2),
    'last_update': time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(current_time)),
    'device_class': 'timestamp'
})

hass.services.call(
    'input_datetime', 
    'set_datetime', 
    {
        'entity_id': 'input_datetime.rce_lowest_window_noon',
        'datetime': min_time_str
    }
)
