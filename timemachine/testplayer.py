import time
from threading import Event

from timemachine import Archivary, config, GD

Archivary.logger.setLevel(10)


track_event = Event()
config.optd = {"COLLECTIONS": ["GratefulDead", "Phish", "PhilLeshandFriends"], "FAVORED_TAPER": "miller"}

archive = Archivary.GDArchive()
tapedate = "1982-11-25"
tapedate = "1980-10-29"
tapes = archive.tape_dates[tapedate]

tape = tapes[9]
tape = tapes[8]

p = GD.GDPlayer(tape)


@p.property_observer("playlist-pos")
def on_track_event(_name, value):
    track_event.set()
    if value == None:
        pass
    print(f"in track event callback {_name}, {value}")


p.seek_to(1, 0.0)

p.fseek(300)

# Start playback.
p.play()

time.sleep(10)

p.pause()

p.seek_to(8, 100.0)

p.status()
p.play()
for i in range(3):
    p.fseek(-30)
