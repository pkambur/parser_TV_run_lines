import json
import os

CHANNELS_FILE = 'channels.json'

def load_channels():
    if not os.path.exists(CHANNELS_FILE):
        return {}
    with open(CHANNELS_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_channels(channels):
    with open(CHANNELS_FILE, 'w', encoding='utf-8') as f:
        json.dump(channels, f, ensure_ascii=False, indent=4)

def add_event(channel, time_str):
    channels = load_channels()
    if channel not in channels:
        return False
    if 'schedule' not in channels[channel]:
        channels[channel]['schedule'] = []
    if time_str not in channels[channel]['schedule']:
        channels[channel]['schedule'].append(time_str)
    save_channels(channels)
    return True

def remove_event(channel, time_str):
    channels = load_channels()
    if channel in channels and 'schedule' in channels[channel]:
        if time_str in channels[channel]['schedule']:
            channels[channel]['schedule'].remove(time_str)
            save_channels(channels)
            return True
    return False

def get_events():
    channels = load_channels()
    return {ch: v.get('schedule', []) for ch, v in channels.items() if 'schedule' in v} 