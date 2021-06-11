import datetime
import logging
import optparse
import os
import re
import string
import subprocess
import sys
from threading import Event
from time import sleep

import board
import digitalio
from adafruit_rgb_display import color565
from adafruit_rgb_display.st7735 import ST7735R
from gpiozero import RotaryEncoder, Button
from PIL import Image, ImageDraw, ImageFont
from tenacity import retry
from tenacity.stop import stop_after_delay
from typing import Callable

import pkg_resources
from timemachine import config, controls


parser = optparse.OptionParser()
parser.add_option('--wpa_path', dest='wpa_path', type="string", default='/etc/wpa_supplicant/wpa_supplicant.conf', help="path to wpa_supplicant file [default %default]")
parser.add_option('-d', '--debug', dest='debug', type="int", default=1, help="If > 0, don't run the main script on loading [default %default]")
parser.add_option('--test', dest='test', action="store_true", default=False, help="Force reconnection (for testing) [default %default]")
parser.add_option('--sleep_time', dest='sleep_time', type="int", default=10, help="how long to sleep before checking network status [default %default]")
parser.add_option('-v', '--verbose', dest='verbose', action="store_true", default=False, help="Print more verbose information [default %default]")
parms, remainder = parser.parse_args()

logging.basicConfig(format='%(asctime)s.%(msecs)03d %(levelname)s: %(name)s %(message)s', level=logging.INFO, datefmt='%Y-%m-%d %H:%M:%S')
logger = logging.getLogger(__name__)
controlsLogger = logging.getLogger('timemachine.controls')
if parms.verbose:
    logger.setLevel(logging.DEBUG)
    controlsLogger.setLevel(logging.DEBUG)
else:
    logger.setLevel(logging.DEBUG)
    controlsLogger.setLevel(logging.INFO)

for k in parms.__dict__.keys():
    print(F"{k:20s} : {parms.__dict__[k]}")


@retry(stop=stop_after_delay(10))
def retry_call(callable: Callable, *args, **kwargs):
    """Retry a call."""
    return callable(*args, **kwargs)


def twist_knob(screen_event: Event, knob: RotaryEncoder, label):
    if knob.is_active:
        logger.debug(f"Knob {label} steps={knob.steps} value={knob.value}")
    else:
        if knob.steps < knob.threshold_steps[0]:
            knob.steps = knob.threshold_steps[0]
        if knob.steps > knob.threshold_steps[1]:
            knob.steps = knob.threshold_steps[1]
        logger.debug(f"Knob {label} is inactive")
    screen_event.set()


def rewind_button(button):
    logger.debug("pressing rewind")
    rewind_event.set()


def select_button(button):
    logger.debug("pressing select")
    select_event.set()


def stop_button(button):
    logger.debug("pressing stop")
    done_event.set()


y = retry_call(RotaryEncoder, config.year_pins[1], config.year_pins[0], max_steps=0, threshold_steps=(-1, 100))
y.when_rotated = lambda x: twist_knob(screen_event, y, "year")
y_button = retry_call(Button, config.year_pins[2])

rewind = retry_call(Button, config.rewind_pin)
select = retry_call(Button, config.select_pin, hold_time=2, hold_repeat=True)
stop = retry_call(Button, config.stop_pin)

rewind.when_pressed = lambda x: rewind_button(x)
select.when_pressed = lambda x: select_button(x)
stop.when_pressed = lambda x: stop_button(x)

rewind_event = Event()
select_event = Event()
done_event = Event()
screen_event = Event()

scr = controls.screen(upside_down=False)
scr.clear()


def select_option(scr, y, message, choices):
    if type(choices) == type(lambda: None): choices = choices()
    scr.clear()
    selected = None
    y.steps = 0
    screen_height = 5
    update_now = scr.update_now
    scr.update_now = False
    done_event.clear()
    rewind_event.clear()
    select_event.clear()

    scr.show_text(message, loc=(0, 0), font=scr.smallfont, color=(0, 255, 255), force=True)
    (text_width, text_height) = scr.smallfont.getsize(message)

    y_origin = text_height*(1+message.count('\n'))
    selection_bbox = controls.Bbox(0, y_origin, 160, 128)

    while not select_event.is_set():
        if rewind_event.is_set():
            choices = choice_fn()
            rewind_event.clear()
        scr.clear_area(selection_bbox, force=False)
        x_loc = 0
        y_loc = y_origin
        step = divmod(y.steps, len(choices))[1]

        text = '\n'.join(choices[max(0, step-int(screen_height/2)):step])
        (text_width, text_height) = scr.oldfont.getsize(text)
        scr.show_text(text, loc=(x_loc, y_loc), font=scr.oldfont, force=False)
        y_loc = y_loc + text_height*(1+text.count('\n'))

        text = choices[step]
        (text_width, text_height) = scr.oldfont.getsize(text)
        scr.show_text(text, loc=(x_loc, y_loc), font=scr.oldfont, color=(0, 0, 255), force=False)
        y_loc = y_loc + text_height

        text = '\n'.join(choices[step+1:min(step+screen_height, len(choices))])
        (text_width, text_height) = scr.oldfont.getsize(text)
        scr.show_text(text, loc=(x_loc, y_loc), font=scr.oldfont, force=True)

        sleep(0.01)
    select_event.clear()
    selected = choices[step]
    #scr.show_text(F"So far: \n{selected}",loc=selected_bbox.origin(),color=(255,255,255),font=scr.smallfont,force=True)

    logger.info(F"word selected {selected}")
    scr.update_now = update_now
    return selected


def select_chars(scr, y, message, message2="So Far", character_set=string.printable):
    scr.clear()
    #character_set = string.printable
    selected = ''
    y.steps = 0
    screen_width = 12
    update_now = scr.update_now
    scr.update_now = False
    done_event.clear()
    select_event.clear()

    scr.show_text(message, loc=(0, 0), font=scr.smallfont, color=(0, 255, 255), force=True)
    (text_width, text_height) = scr.smallfont.getsize(message)

    y_origin = text_height*(1+message.count('\n'))
    selection_bbox = controls.Bbox(0, y_origin, 160, y_origin+22)
    selected_bbox = controls.Bbox(0, y_origin+21, 160, 128)

    while not done_event.is_set():
        while not select_event.is_set() and not done_event.is_set():
            scr.clear_area(selection_bbox, force=False)
            # scr.draw.rectangle((0,0,scr.width,scr.height),outline=0,fill=(0,0,0))
            x_loc = 0
            y_loc = y_origin

            text = 'DEL'
            (text_width, text_height) = scr.oldfont.getsize(text)
            if y.steps < 0:  # we are deleting
                scr.show_text(text, loc=(x_loc, y_loc), font=scr.oldfont, color=(0, 0, 255), force=False)
                scr.show_text(character_set[:screen_width], loc=(x_loc + text_width, y_loc), font=scr.oldfont, force=True)
                continue
            scr.show_text(text, loc=(x_loc, y_loc), font=scr.oldfont, force=False)
            x_loc = x_loc + text_width

            # print the white before the red, if applicable
            text = character_set[max(0, y.steps-int(screen_width/2)):y.steps]
            for x in character_set[94:]:
                text = text.replace(x, u'\u25A1')
            (text_width, text_height) = scr.oldfont.getsize(text)
            scr.show_text(text, loc=(x_loc, y_loc), font=scr.oldfont, force=False)
            x_loc = x_loc + text_width

            # print the red character
            text = character_set[y.steps]
            if text == ' ':
                text = "SPC"
            elif text == '\t':
                text = "\\t"
            elif text == '\n':
                text = "\\n"
            elif text == '\r':
                text = "\\r"
            elif text == '\v':
                text = "\\v"
            elif text == '\f':
                text = "\\f"
            (text_width, text_height) = scr.oldfont.getsize(text)
            scr.show_text(text, loc=(x_loc, y_loc), font=scr.oldfont, color=(0, 0, 255), force=False)
            x_loc = x_loc + text_width

            # print the white after the red, if applicable
            text = character_set[y.steps+1:min(y.steps+screen_width, len(character_set))]
            for x in character_set[94:]:
                text = text.replace(x, u'\u25A1')
            (text_width, text_height) = scr.oldfont.getsize(text)
            scr.show_text(text, loc=(x_loc, y_loc), font=scr.oldfont, force=True)
            x_loc = x_loc + text_width

            sleep(0.1)
        select_event.clear()
        if done_event.is_set():
            continue
        if y.steps < 0:
            selected = selected[:-1]
            scr.clear_area(selected_bbox, force=False)
        else:
            selected = selected + character_set[y.steps]
        scr.show_text(F"{message2}:\n{selected}", loc=selected_bbox.origin(), color=(255, 255, 255), font=scr.oldfont, force=True)

    logger.info(F"word selected {selected}")
    scr.update_now = update_now
    return selected


def wifi_connected(max_attempts=3):
    logger.info("Checking if Wifi connected")
    cmd = "iwconfig"
    connected = False
    attempt = 0
    while not connected and attempt < max_attempts:
        if attempt > 0:
            sleep(parms.sleep_time)
        attempt = attempt + 1
        raw = subprocess.check_output(cmd, shell=True)
        raw = raw.decode()
        address = raw.split("\n")[0].split()[3]
        logger.info(F"wifi address read as {address}")
        connected = '"' in str.replace(address, "ESSID:", "")
    return connected
    # return False


def get_wifi_choices():
    logger.info("Getting Wifi Choices")
    cmd = "sudo iwlist wlan0 scan | grep ESSID:"
    raw = retry_call(subprocess.check_output, cmd, shell=True)
    #raw = subprocess.check_output(cmd,shell=True)
    choices = [x.lstrip().replace('ESSID:', '').replace('"', '') for x in raw.decode().split('\n')]
    choices = [x for x in choices if bool(re.search(r'[a-z,0-9]', x, re.IGNORECASE))]
    choices = choices + ['HIDDEN_WIFI']
    logger.info(F"Wifi Choices {choices}")
    return choices


def update_wpa_conf(wpa_path, wifi, passkey, extra_dict):
    logger.info(F"Updating the wpa_conf file {wpa_path}")
    #if not os.path.exists(wpa_path): raise Exception('File Missing')
    #with open(wpa_path,'r') as f: wpa_lines = [x.rstrip() for x in f.readlines()]
    wpa_lines = ['ctrl_interface=DIR=/var/run/wpa_supplicant GROUP=netdev', 'update_config=1', F'country={extra_dict["country"]}']
    wpa = wpa_lines + ['', 'network={', F'        ssid="{wifi}"', F'        psk="{passkey}"']
    for (k, v) in extra_dict.items():
        if k == 'country':
            continue
        wpa = wpa + [F'        {k}={v}']
    wpa = wpa + ['    }']
    new_wpa_path = os.path.join(os.getenv('HOME'), 'wpa_supplicant.conf')
    f = open(new_wpa_path, 'w')
    f.write('\n'.join(wpa))
    cmd1 = F"sudo cp {wpa_path} {wpa_path}.bak"
    cmd2 = F"sudo mv {new_wpa_path} {wpa_path}"
    raw = subprocess.check_output(cmd1, shell=True)
    raw = subprocess.check_output(cmd2, shell=True)
    cmd = F"sudo chown root {wpa_path}"
    _ = subprocess.check_output(cmd, shell=True)
    cmd = F"sudo chgrp root {wpa_path}"
    _ = subprocess.check_output(cmd, shell=True)


def get_mac_address():
    eth_mac_address = 'fail'
    #wlan_mac_address = 'fail'
    try:
      #cmd = "cat /sys/class/net/eth0/address"
      cmd = "ifconfig -a | awk '/ether/{print $2}'"
      eth_mac_address = subprocess.check_output(cmd, shell=True).decode().strip()
      #cmd = "cat /sys/class/net/wlan0/address"
      #wlan_mac_address = subprocess.check_output(cmd, shell=True).decode().strip()
    except: pass
    return eth_mac_address


def get_ip():
    cmd = "hostname -I"
    ip = subprocess.check_output(cmd, shell=True)
    ip = ip.decode().split(' ')[0]
    return ip


def exit_success(status=0, sleeptime=5):
    sleep(sleeptime)
    sys.exit(status)


def get_wifi_params():
    extra_dict = {}
    country_code = select_option(scr, y, "Country Code\nTurn Year, Select", ['US', 'CA', 'GB', 'AU', 'FR', 'other'])
    if country_code == 'other':
        country_code = select_chars(scr, y, "2 Letter\ncountry code\nSelect. Stop to end", character_set=string.printable[36:62])
    extra_dict['country'] = country_code
    wifi = select_option(scr, y, "Select Wifi Name\nTurn Year, Select", get_wifi_choices)
    if wifi == 'HIDDEN_WIFI':
        wifi = select_chars(scr, y, "Input Wifi Name\nSelect. Stop to end")
    passkey = select_chars(scr, y, "Passkey:Turn Year\nSelect. Stop to end", message2=wifi)
    need_extra_fields = 'no'
    need_extra_fields = select_option(scr, y, "Extra Fields\nRequired?", ['no', 'yes'])
    while need_extra_fields == 'yes':
        fields = ['priority', 'scan_ssid', 'key_mgmt', 'bssid', 'mode', 'proto', 'auth_alg', 'pairwise', 'group', 'eapol_flags', 'eap', 'other']
        field_name = select_option(scr, y, "Field Name\nTurn Year, Select", fields)
        if field_name == 'other':
            field_name = select_chars(scr, y, "Field Name:Turn Year\nSelect. Stop to end")
        field_value = select_chars(scr, y, "Field Value:Turn Year\nSelect. Stop to end", message2=field_name)
        extra_dict[field_name] = field_value
        need_extra_fields = select_option(scr, y, "More Fields\nRequired?", ['no', 'yes'])
    return wifi, passkey, extra_dict


sleep(parms.sleep_time)

#eth_mac_address, wlan_mac_address = get_mac_address()
eth_mac_address = get_mac_address()
scr.show_text(F"Connect wifi")
scr.show_text(F"MAC addresses\neth0, wlan0\n{eth_mac_address}\n{wlan_mac_address}", loc=(0, 30), color=(0, 255, 255), font=scr.smallfont, force=True)
sleep(4)
icounter = 0
while ((not wifi_connected()) and icounter < 3) or (parms.test and icounter < 1):
    scr.clear()
    scr.show_text(F"Wifi not connected\n{icounter}", font=scr.smallfont, force=True)
    icounter = icounter + 1
    wifi, passkey, extra_dict = get_wifi_params()
    scr.clear()
    scr.show_text(F"wifi:\n{wifi}\npasskey:\n{passkey}", loc=(0, 0), color=(255, 255, 255), font=scr.oldfont, force=True)
    update_wpa_conf(parms.wpa_path, wifi, passkey, extra_dict)
    cmd = "sudo killall -HUP wpa_supplicant"
    # os.system(cmd)
    #print(F"command {cmd}")
    if not parms.test:
        os.system(cmd)
    else:
        print(F"not issuing command {cmd}")
    sleep(2*parms.sleep_time)

if wifi_connected():
    ip = get_ip()
    scr.clear()
    scr.show_text(F"Wifi connected\n{ip}", font=scr.smallfont, force=True)
    logger.info(F"Wifi connected\n{ip}")
    exit_success(sleeptime=parms.sleep_time)
else:
    sys.exit(-1)
