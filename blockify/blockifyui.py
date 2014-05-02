# TODO: Minimize to system-tray
# TODO: Different modes: minimal, full
# TODO: Textview: Delete line Ctrl+D, Undo/Redo Ctrl+Z, Ctrl+Y
import codecs
import datetime
import logging
import os
import signal

from dbus.exceptions import DBusException
import glib
import gtk

import blockify
import blockifydbus


log = logging.getLogger("gui")


class Notepad(gtk.Window):

    def __init__(self, location, parentw):

        super(Notepad, self).__init__()

        self.location = location
        self.parentw = parentw  # Parent window, TODO: Create a gtk-parent.

        self.set_title("Blocklist")
        self.set_wmclass("blocklist", "Blockify")
        self.set_default_size(460, 500)
        self.set_position(gtk.WIN_POS_CENTER)

        self.textview = gtk.TextView()
        self.statusbar = gtk.Statusbar()
        self.statusbar.push(0, "Ctrl+S to save, Ctrl+Q/W to close.")

        self.create_keybinds()
        vbox = self.create_layout()

        self.add(vbox)

        self.open_file()
        self.show_all()


        # FIXME: Unholy mess. Why do i have to set value redundantly here?
        swadj = self.sw.get_vadjustment()
        swadj.value = 500
        swadj.set_value(960)

        tvadi = self.textview.get_vadjustment()
        tvadi.value = 500
        tvadi.set_value(960)


    def create_layout(self):
        vbox = gtk.VBox()
        textbox = gtk.VBox()
        statusbox = gtk.VBox()
        vbox.pack_start(textbox, True, True, 0)
        vbox.pack_start(statusbox, False, False, 0)

        # Put the textview into a ScrolledWindow.
        self.sw = gtk.ScrolledWindow()
        self.sw.set_policy(gtk.POLICY_AUTOMATIC, gtk.POLICY_AUTOMATIC)
        self.sw.add(self.textview)
        textbox.pack_start(self.sw)
        statusbox.pack_start(self.statusbar, True, False, 0)

        return vbox


    def create_keybinds(self):
        # Keybindings.
        quit_group = gtk.AccelGroup()
        quit_group.connect_group(ord("q"), gtk.gdk.CONTROL_MASK,
                                 gtk.ACCEL_LOCKED, self.destroy)
        quit_group.connect_group(ord("w"), gtk.gdk.CONTROL_MASK,
                                 gtk.ACCEL_LOCKED, self.destroy)
        self.add_accel_group(quit_group)

        save_group = gtk.AccelGroup()
        save_group.connect_group(ord("s"), gtk.gdk.CONTROL_MASK,
                                 gtk.ACCEL_LOCKED, self.save_file)
        self.add_accel_group(save_group)


    def destroy(self, *args):
        "Overloading destroy to untoggle the Open List button."
        super(Notepad, self).destroy()
        self.parentw.togglelist.set_active(False)


    def open_file(self, *args):
        textbuffer = self.textview.get_buffer()
        with codecs.open(self.location, "r", encoding="utf-8") as f:
            textbuffer.set_text(f.read())
        self.set_title(self.location)


    def save_file(self, *args):
        textbuffer = self.textview.get_buffer()
        start, end = textbuffer.get_start_iter(), textbuffer.get_end_iter()
        text = textbuffer.get_text(start, end)
        if not text.endswith("\n"):
            text += "\n"
        with codecs.open(self.location, "w", encoding="utf-8") as f:
            f.write(text)
        now = str(datetime.datetime.now())
        self.statusbar.push(0, "{}: Saved to {}.".format(now, self.location))


class BlockifyUI(gtk.Window):

    def __init__(self):
        super(BlockifyUI, self).__init__()

        self.use_dbus = True
        self.automute_toggled = False
        self.block_toggled = False
        # Set the GUI/Blockify update interval to 250ms. Increase this to
        # reduce cpu usage resp. increase it to increase responsiveness.
        # If you need absolutely minimal CPU usage you could, in self.start(),
        # change the line to glib.timeout_add_seconds(2, self.update) or more.
        self.update_interval = 250

        self.init_window()
        self.create_buttons()
        vbox = self.create_layout()
        self.add(vbox)

        # Trap the exit.
        self.connect("destroy", self.shutdown)


    def init_window(self):
        basedir = os.path.dirname(os.path.realpath(__file__))
        self.muteofficon = os.path.join(basedir, "data/not_muted.png")
        self.muteonicon = os.path.join(basedir, "data/muted.png")
        self.set_icon_from_file(self.muteofficon)

        # Window setup.
        self.set_title("Blockify")
        self.set_wmclass("blockify", "Blockify")
        self.set_default_size(220, 240)


    def create_buttons(self):
        self.artistlabel = gtk.Label()
        self.titlelabel = gtk.Label()
        self.statuslabel = gtk.Label()
        # Block/Unblock button.
        self.toggleblock = gtk.ToggleButton("Block")
        self.toggleblock.connect("clicked", self.on_toggleblock)

        # Mute/Unmute button.
        self.togglemute = gtk.ToggleButton("(Manual) Mute")
        self.togglemute.connect("clicked", self.on_togglemute)

        # Play/Pause button.
        self.toggleplay = gtk.ToggleButton("Pause")
        self.toggleplay.connect("clicked", self.on_toggleplay)

        # Open/Close Blocklist button.
        self.togglelist = gtk.ToggleButton("Open List")
        self.togglelist.connect("clicked", self.on_togglelist)

        self.nextsong = gtk.Button("Next")
        self.nextsong.connect("clicked", self.on_nextsong)

        self.prevsong = gtk.Button("Previous")
        self.prevsong.connect("clicked", self.on_prevsong)

        # Disable/Enable mute checkbutton.
        self.toggleautomute = gtk.ToggleButton("Disable AutoMute")
        self.toggleautomute.unset_flags(gtk.CAN_FOCUS)
        self.toggleautomute.connect("clicked", self.on_toggleautomute)


    def create_layout(self):
        vbox = gtk.VBox()
        vbox.add(self.artistlabel)
        vbox.add(self.titlelabel)
        vbox.add(self.statuslabel)
        hbox = gtk.HBox()
        vbox.pack_start(hbox)
        vbox.add(self.toggleplay)
        hbox.add(self.prevsong)
        hbox.add(self.nextsong)
        vbox.add(self.toggleblock)
        vbox.add(self.togglemute)
        vbox.add(self.toggleautomute)
        vbox.add(self.togglelist)

        return vbox


    def format_current_song(self):
        song = self.b.current_song
        # For whatever reason, spotify doesn't use a normal hyphen but a
        # slightly longer one. This is its unicode code point.
        delimiter = u"\u2013"

        try:
            artist, title = song.split(" {} ".format(delimiter))
        except (ValueError, IndexError):
            try:
                artist = self.spotify.get_song_artist()
                title = self.spotify.get_song_title()
            except AttributeError:
                artist, title = song, "No song playing?"
                self.use_dbus = False

        return artist, title


    def update(self):
        # Call the main update function of blockify.
        self.blocked = self.b.update()

        # Grab some useful information from DBus.
        try:
            self.songstatus = self.spotify.get_song_status()
            self.use_dbus = True
        except:
            self.songstatus = ""
            self.use_dbus = False

        if self.spotify and self.use_dbus:
            self.statuslabel.set_text(self.get_status_text())

        artist, title = self.format_current_song()

        self.artistlabel.set_text(artist)
        self.titlelabel.set_text(title)
        # Set state label:

        # Correct the state of the Block/Unblock toggle button.
        if self.blocked:
            self.toggleblock.set_active(True)
        elif not self.blocked:
            self.toggleblock.set_active(False)

        # Correct state of Open/Close List toggle button.
        try:
            if not self.n.get_visible() and self.togglelist.get_active():
                self.togglelist.set_active(False)
        except AttributeError:
            pass

        # The glib.timeout loop will only break if we return False here.
        return True


    def get_status_text(self):
        if self.spotify:
            try:
                songlength = self.spotify.get_song_length()
                m, s = divmod(songlength, 60)
                r = self.spotify.get_property("Metadata")["xesam:autoRating"]
                return "{}m{}s, {} ({})".format(m, s, r, self.songstatus)
            except (TypeError, DBusException) as e:
                log.error("Cannot use DBus. Some features (PlayPause etc.) "
                          "will be unavailable ({}).".format(e))
                return ""
        else:
            return ""


    def connect_dbus(self):
        try:
            self.spotify = blockifydbus.BlockifyDBus()
        except Exception as e:
            log.error("Cannot connect to DBus. Some features (PlayPause etc.) "
                      "will be unavailable ({}).".format(e))
            self.spotify = None
            self.use_dbus = False

    def start(self):
        "Start blockify and the main update routine."
        # Try to find a Spotify process in the current DBus session.

        self.connect_dbus()
        blocklist = blockify.Blocklist()
        self.b = blockify.Blockify(blocklist)
        self.bind_signals()
        self.b.toggle_mute()
        # Start and loop the main update routine once every 250ms.
        # To influence responsiveness or CPU usage, decrease/increase ms here.
        glib.timeout_add(self.update_interval, self.update)


    def bind_signals(self):
        signal.signal(signal.SIGUSR1, lambda sig, hdl: self.b.block_current())
        signal.signal(signal.SIGTERM, lambda sig, hdl: self.shutdown())
        signal.signal(signal.SIGINT, lambda sig, hdl: self.shutdown())


    def shutdown(self, *args):
        "Cleanly shut down, unmuting sound and saving the blocklist."
        self.b.shutdown()
        gtk.main_quit()


    def on_toggleautomute(self, widget):
        if widget.get_active():
            self.set_title("Blockify (inactive)")
            self.b.automute = False
            self.automute_toggled = False
            self.block_toggled = False
            lbl = self.toggleblock.get_label()
            self.toggleblock.set_label(lbl + " (disabled)")
            widget.set_label("Enable AutoMute")
            self.b.toggle_mute()
        else:
            self.set_title("Blockify")
            self.b.automute = True
            self.automute_toggled = True
            self.toggleblock.set_label("Block")
            widget.set_label("Disable AutoMute")


    def on_toggleblock(self, widget):
        if self.b.automute:
            if widget.get_active():
                widget.set_label("Unblock")
                if not self.blocked:
                    self.b.block_current()
                if not self.block_toggled:
                    self.set_icon_from_file(self.muteonicon)
                    self.set_title("Blockify (blocked)")
                    self.block_toggled = True
            else:
                widget.set_label("Block")
                if self.blocked:
                    self.b.unblock_current()
                if self.block_toggled:
                    self.set_icon_from_file(self.muteofficon)
                    self.set_title("Blockify")
                    self.block_toggled = False


    def on_togglemute(self, widget):
        if self.block_toggled:
            return
        if widget.get_active():
            widget.set_label("Unmute")
            self.b.automute = False
            self.b.toggle_mute(True)
            self.set_icon_from_file(self.muteonicon)
            if self.automute_toggled:
                self.set_title("Blockify (muted)")
        else:
            widget.set_label("Mute")
            self.set_icon_from_file(self.muteofficon)
            self.b.toggle_mute(False)
            if self.automute_toggled:
                self.b.automute = True
                self.set_title("Blockify")


    def on_togglelist(self, widget):
        if widget.get_active():
            widget.set_label("Close List")
            self.n = Notepad(self.b.blocklist.location, self)
        else:
            widget.set_label("Open List")
            if self.n:
                self.n.destroy()


    def on_toggleplay(self, widget):
        # Try to connect to dbus if it failed before.
        if not self.spotify:
            self.connect_dbus()
        if self.spotify and self.use_dbus:
            if self.songstatus == "Playing":
                widget.set_label("Play")
            else:
                widget.set_label("Pause")
            self.spotify.playpause()


    def on_nextsong(self, widget):
        if not self.spotify:
            self.connect_dbus()
        if self.spotify and self.use_dbus:
            self.spotify.next()


    def on_prevsong(self, widget):
        if not self.spotify:
            self.connect_dbus()
        if self.spotify and self.use_dbus:
            self.spotify.prev()


def main():
    # Edit this for less or more logging. Loglevel 0 is least verbose.
    blockify.init_logger(logpath=None, loglevel=2, quiet=False)
    ui = BlockifyUI()
    ui.show_all()
    ui.start()
    gtk.main()


if __name__ == "__main__":
    main()
