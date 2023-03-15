import logging
import optparse
import os
import re
import string
import subprocess
import sys

from tenacity import retry
from tenacity.retry import retry_if_result
from tenacity.stop import stop_after_attempt, stop_after_delay
from tenacity.wait import wait_random
from typing import Callable

from timemachine import controls


parser = optparse.OptionParser()
parser.add_option(
    "--wpa_path",
    dest="wpa_path",
    type="string",
    default="/etc/wpa_supplicant/wpa_supplicant.conf",
    help="path to wpa_supplicant file [default %default]",
)
parser.add_option(
    "-d",
    "--debug",
    dest="debug",
    type="int",
    default=1,
    help="If > 0, don't run the main script on loading [default %default]",
)
parser.add_option(
    "--test",
    dest="test",
    action="store_true",
    default=False,
    help="Force reconnection (for testing) [default %default]",
)
parser.add_option(
    "--sleep_time",
    dest="sleep_time",
    type="int",
    default=10,
    help="how long to sleep before checking network status [default %default]",
)
parser.add_option(
    "-v",
    "--verbose",
    dest="verbose",
    action="store_true",
    default=False,
    help="Print more verbose information [default %default]",
)
parms, remainder = parser.parse_args()

logging.basicConfig(
    format="%(asctime)s.%(msecs)03d %(levelname)s: %(name)s %(message)s",
    level=logging.INFO,
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)
controlsLogger = logging.getLogger("timemachine.controls")
if parms.verbose:
    logger.setLevel(logging.DEBUG)
    controlsLogger.setLevel(logging.DEBUG)
else:
    logger.setLevel(logging.DEBUG)
    controlsLogger.setLevel(logging.INFO)

for k in parms.__dict__.keys():
    print(f"{k:20s} : {parms.__dict__[k]}")


@retry(stop=stop_after_delay(10))
def retry_call(callable: Callable, *args, **kwargs):
    """Retry a call."""
    return callable(*args, **kwargs)


def return_last_value(retry_state):
    """return the result of the last call made in a tenacity retry"""
    return retry_state.outcome.result()


@retry(
    stop=stop_after_attempt(7),
    wait=wait_random(min=1, max=2),
    retry=retry_if_result(lambda x: not x),
    retry_error_callback=return_last_value,
)
def retry_until_true(callable: Callable, *args, **kwargs):
    return callable(*args, **kwargs)


max_choices = len(string.printable)
TMB = controls.Time_Machine_Board(
    mdy_bounds=[(0, 9), (0, 1 + divmod(max_choices - 1, 10)[0]), (0, 9)], screen_desc={"psychedelic_row": False}
)

TMB.rewind.when_pressed = lambda x: TMB.rewind_button(x)
TMB.rewind.when_held = lambda x: TMB.rewind_button(x)
TMB.ffwd.when_pressed = lambda x: TMB.ffwd_button(x)
TMB.play_pause.when_pressed = lambda x: TMB.play_pause_button(x)
TMB.y_button.when_pressed = lambda x: TMB.year_button(x)
TMB.m_button.when_pressed = lambda x: TMB.month_button(x)
TMB.d_button.when_pressed = lambda x: TMB.day_button(x)
TMB.select.when_pressed = lambda x: TMB.select_button(x)
TMB.stop.when_pressed = lambda x: TMB.stop_button(x)

counter = controls.decade_counter(TMB.d, TMB.y, bounds=(0, 100))
TMB.m.when_rotated = lambda x: TMB.decade_knob(TMB.m, "month", counter)
TMB.d.when_rotated = lambda x: TMB.decade_knob(TMB.d, "day", counter)
TMB.y.when_rotated = lambda x: TMB.decade_knob(TMB.y, "year", counter)


def wifi_connected(max_attempts=1):
    wifi_conn = False
    TMB.scr.show_text("Checking for\nWifi connection", font=TMB.scr.smallfont, force=True, clear=True)
    if not os.path.exists(parms.wpa_path):
        return False
    logger.info("Checking if Wifi connected")
    cmd = "iwconfig"
    attempt = 0
    while not wifi_conn and attempt < max_attempts:
        if attempt > 0:
            cmd2 = "sudo killall -HUP wpa_supplicant"
            if not parms.test:
                os.system(cmd2)
                button_press = sleep_or_button(parms.sleep_time)
                if button_press:
                    return wifi_conn
        attempt = attempt + 1
        raw = subprocess.check_output(cmd, shell=True)
        raw = raw.decode("utf-8")
        address = raw.split("\n")[0].split()[3]
        logger.info(f"wifi address read as {address}")
        wifi_conn = '"' in str.replace(address, "ESSID:", "")
    return wifi_conn


def get_wifi_choices():
    logger.info("Getting Wifi Choices")
    cmd = "sudo iwlist wlan0 scan | grep ESSID:"
    raw = retry_call(subprocess.check_output, cmd, shell=True)
    # choices = [x.lstrip().replace(b'ESSID:', b'').replace(b'"', b'') for x in raw.split(b'\n')]
    choices = [x.lstrip().replace("ESSID:", "").replace('"', "") for x in raw.decode("utf-8").split("\n")]
    choices = [x for x in choices if bool(re.search(r"[a-z,0-9]", x, re.IGNORECASE))]
    choices = list(dict.fromkeys(choices))  # distinct
    choices = sorted(choices, key=str.casefold)
    choices = choices + ["HIDDEN_WIFI"]
    logger.info(f"Wifi Choices {choices}")
    return choices


def update_wpa_conf(wpa_path, wifi, passkey, extra_dict):
    logger.info(f"Updating the wpa_conf file {wpa_path}")
    wpa_lines = [
        "ctrl_interface=DIR=/var/run/wpa_supplicant GROUP=netdev",
        "update_config=1",
        f'country={extra_dict["country"]}',
    ]
    if "\\x" in wifi:
        wifi_hex = (
            wifi.encode("utf-8").decode("unicode-escape").encode("ISO-8859-1").hex()
        )  # unbelievable!! Thank you Google.
        wpa = wpa_lines + ["", "network={", f"        ssid={wifi_hex}"]
    else:
        wpa = wpa_lines + ["", "network={", f'        ssid="{wifi}"']
    if len(passkey) == 0:
        wpa = wpa + ["        key_mgmt=NONE\n        priority=0\n"]
    else:
        wpa = wpa + [f'        psk="{passkey}"']
    for (k, v) in extra_dict.items():
        if k == "country":
            continue
        wpa = wpa + [f"        {k}={v}"]
    wpa = wpa + ["    }\n"]
    new_wpa_path = os.path.join(os.getenv("HOME"), "wpa_supplicant.conf")
    f = open(new_wpa_path, "w")
    f.write("\n".join(wpa))
    cmd = f"sudo mv {new_wpa_path} {wpa_path}"
    _ = subprocess.check_output(cmd, shell=True)
    cmd = f"sudo chown root {wpa_path}"
    _ = subprocess.check_output(cmd, shell=True)
    cmd = f"sudo chgrp root {wpa_path}"
    _ = subprocess.check_output(cmd, shell=True)


def get_mac_address():
    eth_mac_address = "fail"
    try:
        # cmd = "cat /sys/class/net/eth0/address"
        cmd = "ifconfig -a | awk '/ether/{print $2}'"
        eth_mac_address = subprocess.check_output(cmd, shell=True).decode().strip()
        # cmd = "cat /sys/class/net/wlan0/address"
        # wlan_mac_address = subprocess.check_output(cmd, shell=True).decode().strip()
    except Exception:
        pass
    return eth_mac_address


def get_ip():
    cmd = "hostname -I"
    ip = subprocess.check_output(cmd, shell=True)
    ip = ip.decode().split(" ")[0]
    if not re.match(r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}", ip):
        ip = None
    return ip


def exit_success(status=0, sleeptime=5):
    sleep_or_button(sleeptime)
    sys.exit(status)


def get_wifi_params():
    extra_dict = {}
    country_code = controls.select_option(
        TMB, counter, "Country Code\nTurn Year, Select", ["US", "CA", "GB", "AU", "FR", "other"]
    )
    if country_code == "other":
        country_code = controls.select_chars(
            TMB, counter, "2 Letter\ncountry code\nSelect. Stop to end", character_set=string.printable[36:62]
        )
    extra_dict["country"] = country_code
    TMB.scr.show_text(
        "scanning networks\nPress rewind\nat any time\nto re-scan",
        font=TMB.scr.smallfont,
        color=(0, 255, 255),
        force=True,
        clear=True,
    )
    sleep_or_button(1)
    wifi = controls.select_option(TMB, counter, "Select Wifi Name\nTurn Year, Select", get_wifi_choices)
    if wifi == "HIDDEN_WIFI":
        wifi = controls.select_chars(TMB, counter, "Input Wifi Name\nSelect. Stop to end")

    passkey = controls.select_chars(TMB, counter, "Passkey:Turn Year\nSelect. Stop to end", message2=wifi)
    need_extra_fields = "no"
    need_extra_fields = controls.select_option(TMB, counter, "Extra Fields\nRequired?", ["no", "yes"])
    while need_extra_fields == "yes":
        fields = [
            "priority",
            "scan_ssid",
            "key_mgmt",
            "bssid",
            "mode",
            "proto",
            "auth_alg",
            "pairwise",
            "group",
            "eapol_flags",
            "eap",
            "other",
        ]
        field_name = controls.select_option(TMB, counter, "Field Name\nTurn Year, Select", fields)
        if field_name == "other":
            field_name = controls.select_chars(TMB, counter, "Field Name:Turn Year\nSelect. Stop to end")
        field_value = controls.select_chars(
            TMB, counter, "Field Value:Turn Year\nSelect. Stop to end", message2=field_name
        )
        extra_dict[field_name] = field_value
        need_extra_fields = controls.select_option(TMB, counter, "More Fields\nRequired?", ["no", "yes"])
    return wifi, passkey, extra_dict


def sleep_or_button(seconds):
    TMB.button_event.clear()
    status = TMB.button_event.wait(seconds)
    TMB.button_event.clear()
    return status


def main():
    try:
        TMB.scr.show_text("Connecting\nto WiFi", font=TMB.scr.font, force=True, clear=True)
        cmd = "sudo rfkill unblock wifi"
        os.system(cmd)
        cmd = "sudo ifconfig wlan0 up"
        os.system(cmd)
        ip = get_ip()
        connected = ip is not None
        if not connected:
            connected = wifi_connected(max_attempts=4)

        eth_mac_address = get_mac_address()
        TMB.scr.show_text(
            f"MAC addresses\neth0\n{eth_mac_address}",
            color=(0, 255, 255),
            font=TMB.scr.smallfont,
            force=True,
            clear=True,
        )
        sleep_or_button(1)
        if parms.test or not connected:
            wifi, passkey, extra_dict = get_wifi_params()
            TMB.scr.show_text(
                f"wifi:\n{wifi}\npasskey:\n{passkey}",
                loc=(0, 0),
                color=(255, 255, 255),
                font=TMB.scr.oldfont,
                force=True,
                clear=True,
            )
            update_wpa_conf(parms.wpa_path, wifi, passkey, extra_dict)
            cmd = "sudo killall -HUP wpa_supplicant"
            if not parms.test:
                os.system(cmd)
            else:
                print(f"not issuing command {cmd}")
            TMB.scr.show_text(
                "wifi connecting\n...",
                loc=(0, 0),
                color=(255, 255, 255),
                font=TMB.scr.smallfont,
                force=True,
                clear=True,
            )
            sleep_or_button(parms.sleep_time)
    except Exception as e:
        logger.exception(e)
        sys.exit(-1)
    finally:
        TMB.clear_events()
        TMB.scr.clear()

    if connected or wifi_connected():
        i = 0
        while ip is None and i < 5:
            ip = get_ip()
            i = i + 1
            sleep_or_button(2)
        logger.info(f"Wifi connected\n{ip}")
        TMB.scr.show_text(f"Wifi connected\n{ip}", font=TMB.scr.smallfont, force=True, clear=True)
        exit_success(sleeptime=0.5 * parms.sleep_time)
    else:
        TMB.scr.show_text("Wifi connection\n\n\nRebooting", font=TMB.scr.smallfont, force=True, clear=True)
        cmd = "sudo reboot"
        os.system(cmd)
        sys.exit(-1)


if __name__ == "__main__" and parms.debug == 0:
    main()
