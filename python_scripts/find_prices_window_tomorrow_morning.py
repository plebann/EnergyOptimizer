current_time = time.time()
today_date = time.strftime("%Y-%m-%d", time.localtime(current_time))
prices = hass.states.get('sensor.rce_prices_tomorrow').attributes['value']

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
hass.states.set('sensor.highest_price_tomorrow_morning', round(max_avg_morn, 2), {
    'friendly_name': 'Highest Price Tomorrow Morning',
    'window_starts': morning_iso,
    'last_update': time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(current_time))
})