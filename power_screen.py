"""Screen power toggle przez fb0/blank — POWER button (event0) wygasza ekran
bez zamykania aplikacji.

Użycie:
    pwr = ScreenPowerToggle()

    # w pętli głównej:
    pwr.poll()
    pwr.tick(sdl2.SDL_GetTicks())
    if pwr.is_off:
        sdl2.SDL_Delay(50)
        continue   # pomiń render

    # w cleanup / quit:
    pwr.restore()
"""
import select
from pathlib import Path

POWER_KEY = 116
FB_BLANK  = '/sys/class/graphics/fb0/blank'
RE_WRITE_MS = 200   # ponów fb0/blank=4 co 200ms (kernel czasem przywraca)


class ScreenPowerToggle:
    def __init__(self, event_path: str = '/dev/input/event0'):
        self._screen_off = False
        self._last_write = 0
        self._pwr = None
        try:
            import evdev
            self._pwr = evdev.InputDevice(event_path)
            try:
                self._pwr.grab()
            except Exception:
                pass
        except Exception:
            self._pwr = None

    @property
    def is_off(self) -> bool:
        return self._screen_off

    def poll(self) -> bool:
        """Sprawdź event0; jeśli POWER naciśnięty — toggle. Zwraca True gdy zmiana stanu."""
        if not self._pwr:
            return False
        try:
            if not select.select([self._pwr.fd], [], [], 0)[0]:
                return False
            changed = False
            for e in self._pwr.read():
                if e.type == 1 and e.code == POWER_KEY and e.value == 1:
                    self._screen_off = not self._screen_off
                    self._write()
                    changed = True
            return changed
        except OSError:
            return False

    def tick(self, now_ms: int):
        """Wywołaj co cykl pętli — gdy ekran ma być OFF, ponawiaj fb0/blank=4
        co RE_WRITE_MS żeby kernel nie przywrócił."""
        if self._screen_off and now_ms - self._last_write >= RE_WRITE_MS:
            self._write()

    def _bl(self, on: bool):
        """Gasi/zapala podświetlenie LED (sunxi disp ioctl /dev/disp). Przy ZAPALANIU
        przywraca zapisaną jasność (SET_BRIGHTNESS) — inaczej samo DISABLE/ENABLE zostawia
        SYSTEMOWĄ regulację jasności 'zaciętą' (MOD-139). fb0/blank gasi tylko obraz.
        DISABLE=0x105 ENABLE=0x104 GET=0x103 SET=0x102, arg=4×long (ekran 0)."""
        import os, fcntl, struct
        try:
            fd = os.open('/dev/disp', os.O_RDWR)
            try:
                if on:
                    fcntl.ioctl(fd, 0x104, struct.pack('@4L', 0, 0, 0, 0))       # ENABLE
                    b = getattr(self, '_bl_bri', None)
                    if b:
                        fcntl.ioctl(fd, 0x102, struct.pack('@4L', 0, b, 0, 0))   # restore jasność
                    self._bl_bri = None
                else:
                    if getattr(self, '_bl_bri', None) is None:   # zapisz jasność TYLKO przy wejściu w OFF
                        try:
                            buf = bytearray(struct.pack('@4L', 0, 0, 0, 0))
                            v = fcntl.ioctl(fd, 0x103, buf, True)                # GET_BRIGHTNESS
                            self._bl_bri = v if isinstance(v, int) and v > 0 else None
                        except Exception:
                            self._bl_bri = None
                    fcntl.ioctl(fd, 0x105, struct.pack('@4L', 0, 0, 0, 0))       # DISABLE
            finally:
                os.close(fd)
        except Exception:
            pass

    def _write(self):
        try:
            Path(FB_BLANK).write_text('4' if self._screen_off else '0')
            self._bl(not self._screen_off)   # realnie gasi/zapala LED (fb0/blank nie wystarcza)
            from time import monotonic
            # bez czytania zegara z SDL — używamy własnego stamp dla tick()
            self._last_write = int(monotonic() * 1000)
        except Exception:
            pass

    def restore(self):
        """Przywróć ekran ON i zwolnij grab. Wywołać przy zamykaniu apki."""
        try:
            Path(FB_BLANK).write_text('0')
            self._bl(True)   # zapal podświetlenie przy wyjściu
        except Exception:
            pass
        if self._pwr is not None:
            try:
                self._pwr.ungrab()
            except Exception:
                pass
            self._pwr = None
