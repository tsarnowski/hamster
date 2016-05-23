#!/usr/bin/env python2
# - coding: utf-8 -

# Copyright (C) 2009-2012 Toms Bauģis <toms.baugis at gmail.com>
# Copyright (C) 2009 Patryk Zawadzki <patrys at pld-linux.org>

# This file is part of Project Hamster.

# Project Hamster is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

# Project Hamster is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with Project Hamster.  If not, see <http://www.gnu.org/licenses/>.
import logging
import datetime as dt

import gtk, gobject
import locale

from hamster.configuration import runtime, dialogs, conf, load_ui_file
from hamster import widgets
from hamster.lib import Fact, trophies, stuff
import hamster.tray as tray

try:
    import wnck
except:
    logging.warning("Could not import wnck - workspace tracking will be disabled")
    wnck = None



class DailyView(object):
    def __init__(self):
        # initialize the window.  explicitly set it to None first, so that the
        # creator knows it doesn't yet exist.
        self.window = None
        self.create_hamster_window()

        self.new_name.grab_focus()

        # configuration
        self.workspace_tracking = conf.get("workspace_tracking")

        conf.connect('conf-changed', self.on_conf_changed)

        # Load today's data, activities and set label
        self.last_activity = None
        self.todays_facts = None

        runtime.storage.connect('activities-changed',self.after_activity_update)
        runtime.storage.connect('facts-changed',self.after_fact_update)
        runtime.storage.connect('toggle-called', self.on_toggle_called)

        self.screen = None
        if self.workspace_tracking:
            self.init_workspace_tracking()


        # refresh hamster every 60 seconds
        gobject.timeout_add_seconds(60, self.refresh_hamster)

        self.prev_size = None

        # bindings
        self.accel_group = self.get_widget("accelgroup")
        self.window.add_accel_group(self.accel_group)

        gtk.accel_map_add_entry("<hamster-time-tracker>/tracking/add", gtk.keysyms.n, gtk.gdk.CONTROL_MASK)
        gtk.accel_map_add_entry("<hamster-time-tracker>/tracking/overview", gtk.keysyms.o, gtk.gdk.CONTROL_MASK)
        gtk.accel_map_add_entry("<hamster-time-tracker>/tracking/stats", gtk.keysyms.i, gtk.gdk.CONTROL_MASK)
        gtk.accel_map_add_entry("<hamster-time-tracker>/tracking/close", gtk.keysyms.Escape, 0)
        gtk.accel_map_add_entry("<hamster-time-tracker>/tracking/quit", gtk.keysyms.q, gtk.gdk.CONTROL_MASK)
        gtk.accel_map_add_entry("<hamster-time-tracker>/edit/prefs", gtk.keysyms.p, gtk.gdk.CONTROL_MASK)
        gtk.accel_map_add_entry("<hamster-time-tracker>/help/contents", gtk.keysyms.F1, 0)



        # create the status icon
        self.statusicon = tray.get_status_icon(self)

        self.reposition_hamster_window()
        self.show_hamster_window()
        self.statusicon.show()

    def create_hamster_window(self):
        if self.window is None:
            # load window of activity switcher and todays view
            self._gui = load_ui_file("today.ui")
            self.window = self._gui.get_object('hamster-window')
            self.window.connect("delete_event", self.on_delete_window)

            gtk.window_set_default_icon_name("hamster-time-tracker")

            self.new_name = widgets.ActivityEntry()
            self.new_name.connect("value-entered", self.on_switch_activity_clicked)
            widgets.add_hint(self.new_name, _("Activity"))
            self.get_widget("new_name_box").add(self.new_name)
            self.new_name.connect("changed", self.on_activity_text_changed)

            self.new_tags = widgets.TagsEntry()
            self.new_tags.connect("tags_selected", self.on_switch_activity_clicked)
            widgets.add_hint(self.new_tags, _("Tags"))
            self.get_widget("new_tags_box").add(self.new_tags)

            self.tag_box = widgets.TagBox(interactive = False)
            self.get_widget("tag_box").add(self.tag_box)

            self.view = widgets.FactTree()
            self.view.connect("key-press-event", self.on_todays_keys)
            self.view.connect("edit-clicked", self._open_edit_activity)
            self.view.connect("row-activated", self.on_today_row_activated)

            self.get_widget("today_box").add(self.view)

            # connect the accelerators
            self.accel_group = self.get_widget("accelgroup")
            self.window.add_accel_group(self.accel_group)

            self._gui.connect_signals(self)

    def reposition_hamster_window(self):
        if not self.window:
            self.create_hamster_window()

        if conf.get("standalone_window_maximized"):
            self.window.maximize()
        else:
            window_box = conf.get("standalone_window_box")
            if window_box:
                x,y,w,h = (int(i) for i in window_box)
                self.window.move(x, y)
                self.window.move(x, y)
                self.window.resize(w, h)
            else:
                self.window.set_position(gtk.WIN_POS_CENTER)

    def toggle_hamster_window(self):
        if not self.window:
            self.show_hamster_window()
        else:
            self.close_window()

    def show_hamster_window(self):
        if not self.window:
            self.create_hamster_window()
            self.reposition_hamster_window()

        self.window.hide_all()
        self.window.show_all()
        self.refresh_hamster()
        self.window.present()

    def init_workspace_tracking(self):
        if not wnck: # can't track if we don't have the trackable
            return

        self.screen = wnck.screen_get_default()
        self.screen.workspace_handler = self.screen.connect("active-workspace-changed", self.on_workspace_changed)
        self.workspace_activities = {}

    """UI functions"""
    def refresh_hamster(self):
        """refresh hamster every x secs - load today, check last activity etc."""
        try:
            if self.window:
                self.load_day()
        except Exception, e:
            logging.error("Error while refreshing: %s" % e)
        finally:  # we want to go on no matter what, so in case of any error we find out about it sooner
            return True

    def load_day(self):
        """sets up today's tree and fills it with records
           returns information about last activity"""
        facts = self.todays_facts = runtime.storage.get_todays_facts()

        self.view.detach_model()

        if facts and facts[-1].end_time == None:
            self.last_activity = facts[-1]
        else:
            self.last_activity = None

        by_category = {}
        for fact in facts:
            duration = 24 * 60 * fact.delta.days + fact.delta.seconds / 60
            by_category[fact.category] = \
                          by_category.setdefault(fact.category, 0) + duration
            self.view.add_fact(fact)

        self.view.attach_model()

        if not facts:
            self._gui.get_object("today_box").hide()
            self._gui.get_object("fact_totals").set_text(_("No records today"))
        else:
            self._gui.get_object("today_box").show()
            total_strings = []
            for category in sorted(by_category):
                # listing of today's categories and time spent in them
                duration = locale.format("%.1f", (by_category[category] / 60.0))
                total_strings.append(_("%(duration)s: %(category)s") % \
                        ({'category': category,
                          #duration in main drop-down per category in hours
                          'duration': _("%sh") % duration
                          }))

            total_string = "\n".join(total_strings)
            self._gui.get_object("fact_totals").set_text(total_string)

        self.set_last_activity()


    def set_last_activity(self):
        activity = self.last_activity
        #sets all the labels and everything as necessary
        self.get_widget("stop_tracking").set_sensitive(activity != None)


        if activity:
            self.get_widget("switch_activity").show()
            self.get_widget("start_tracking").hide()

            delta = dt.datetime.now() - activity.start_time
            duration = delta.seconds /  60

            if activity.category != _("Unsorted"):
                self.get_widget("last_activity_name").set_text("%s - %s" % (activity.activity, activity.category))
            else:
                self.get_widget("last_activity_name").set_text(activity.activity)

            self.get_widget("last_activity_duration").set_text(stuff.format_duration(duration) or _("Just started"))
            self.get_widget("last_activity_description").set_text(activity.description or "")
            self.get_widget("activity_info_box").show()

            self.tag_box.draw(activity.tags)
        else:
            self.get_widget("switch_activity").hide()
            self.get_widget("start_tracking").show()

            self.get_widget("last_activity_name").set_text(_("No activity"))

            self.get_widget("activity_info_box").hide()

            self.tag_box.draw([])


    def delete_selected(self):
        fact = self.view.get_selected_fact()
        runtime.storage.remove_fact(fact.id)


    """events"""
    def on_todays_keys(self, tree, event):
        if (event.keyval == gtk.keysyms.Delete):
            self.delete_selected()
            return True

        return False

    def _open_edit_activity(self, row, fact):
        """opens activity editor for selected row"""
        dialogs.edit.show(self.window, fact_id = fact.id)

    def on_today_row_activated(self, tree, path, column):
        fact = tree.get_selected_fact()
        fact = Fact(fact.activity,
                          category = fact.category,
                          description = fact.description,
                          tags = ", ".join(fact.tags))
        if fact.activity:
            runtime.storage.add_fact(fact)

    def on_add_activity_clicked(self, button):
        dialogs.edit.show(self.window)

    def on_show_overview_clicked(self, button):
        dialogs.overview.show(self.window)


    """button events"""
    def on_menu_add_earlier_activate(self, menu):
        dialogs.edit.show(self.window)
    def on_menu_overview_activate(self, menu_item):
        dialogs.overview.show(self.window)
    def on_menu_about_activate(self, component):
        dialogs.about.show(self.window)
    def on_menu_statistics_activate(self, component):
        dialogs.stats.show(self.window)
    def on_menu_preferences_activate(self, menu_item):
        dialogs.prefs.show(self.window)
    def on_menu_help_contents_activate(self, *args):
        gtk.show_uri(gtk.gdk.Screen(), "ghelp:hamster-time-tracker", 0L)
        trophies.unlock("basic_instructions")


    """signals"""
    def after_activity_update(self, widget):
        self.new_name.refresh_activities()
        self.load_day()

    def after_fact_update(self, event):
        self.load_day()

    def on_workspace_changed(self, screen, previous_workspace):
        if not previous_workspace:
            # wnck has a slight hiccup on init and after that calls
            # workspace changed event with blank previous state that should be
            # ignored
            return

        if not self.workspace_tracking:
            return # default to not doing anything

        current_workspace = screen.get_active_workspace()

        # rely on workspace numbers as names change
        prev = previous_workspace.get_number()
        new = current_workspace.get_number()

        # on switch, update our mapping between spaces and activities
        self.workspace_activities[prev] = self.last_activity


        activity = None
        if "name" in self.workspace_tracking:
            # first try to look up activity by desktop name
            mapping = conf.get("workspace_mapping")

            fact = None
            if new < len(mapping):
                fact = Fact(mapping[new])

                if fact.activity:
                    category_id = None
                    if fact.category:
                        category_id = runtime.storage.get_category_id(fact.category)

                    activity = runtime.storage.get_activity_by_name(fact.activity,
                                                                    category_id,
                                                                    resurrect = False)
                    if activity:
                        # we need dict below
                        activity = dict(name = activity.name,
                                        category = activity.category,
                                        description = fact.description,
                                        tags = fact.tags)


        if not activity and "memory" in self.workspace_tracking:
            # now see if maybe we have any memory of the new workspace
            # (as in - user was here and tracking Y)
            # if the new workspace is in our dict, switch to the specified activity
            if new in self.workspace_activities and self.workspace_activities[new]:
                activity = self.workspace_activities[new]

        if not activity:
            return

        # check if maybe there is no need to switch, as field match:
        if self.last_activity and \
           self.last_activity.name.lower() == activity.name.lower() and \
           (self.last_activity.category or "").lower() == (activity.category or "").lower() and \
           ", ".join(self.last_activity.tags).lower() == ", ".join(activity.tags).lower():
            return

        # ok, switch
        fact = Fact(activity.name,
                          tags = ", ".join(activity.tags),
                          category = activity.category,
                          description = activity.description);
        runtime.storage.add_fact(fact)


    def on_toggle_called(self, client):
        self.window.present()

    def on_conf_changed(self, event, key, value):
        if key == "day_start_minutes":
            self.load_day()

        elif key == "workspace_tracking":
            self.workspace_tracking = value
            if self.workspace_tracking and not self.screen:
                self.init_workspace_tracking()
            elif not self.workspace_tracking:
                if self.screen:
                    self.screen.disconnect(self.screen.workspace_handler)
                    self.screen = None

    def on_activity_text_changed(self, widget):
        self.get_widget("switch_activity").set_sensitive(widget.get_text() != "")

    def on_switch_activity_clicked(self, widget):
        activity, temporary = self.new_name.get_value()

        fact = Fact(activity,
                          tags = self.new_tags.get_text().decode("utf8", "replace"))
        if not fact.activity:
            return

        runtime.storage.add_fact(fact, temporary)
        self.new_name.set_text("")
        self.new_tags.set_text("")

    def on_stop_tracking_clicked(self, widget):
        runtime.storage.stop_tracking()
        self.last_activity = None

    def on_window_configure_event(self, window, event):
        self.view.fix_row_heights()

    def show(self):
        self.window.hide_all()
        self.window.show_all()
        self.window.present()

    def get_widget(self, name):
        return self._gui.get_object(name)

    def on_more_info_button_clicked(self, *args):
        gtk.show_uri(gtk.gdk.Screen(), "ghelp:hamster-time-tracker#input", 0L)
        return False

    def save_window_position(self):
        # properly saving window state and position
        maximized = self.window.get_window().get_state() & gtk.gdk.WINDOW_STATE_MAXIMIZED
        conf.set("standalone_window_maximized", maximized)

        # make sure to remember dimensions only when in normal state
        if maximized == False and not self.window.get_window().get_state() & gtk.gdk.WINDOW_STATE_ICONIFIED:
            x, y = self.window.get_position()
            w, h = self.window.get_size()
            conf.set("standalone_window_box", [x, y, w, h])

    def quit_app(self, *args):
        self.save_window_position()

        # quit the application
        gtk.main_quit()

    def close_window(self, *args):
        self.save_window_position()
        self.window.destroy()
        self.window = None

    def on_delete_window(self, event, data):
        self.save_window_position()
        self.window.destroy()
        self.window = None
        
#        # show the status tray icon
#        activity = self.get_widget("last_activity_name").get_text()
#        self.statusicon.set_tooltip(activity)
#        self.statusicon.set_visible(True)
