# - coding: utf-8 -

# Copyright (C) 2007 Patryk Zawadzki <patrys at pld-linux.org>
# Copyright (C) 2008, 2010 Toms Bauģis <toms.baugis at gmail.com>

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
from configuration import conf
import gobject
import re
import dbus, dbus.mainloop.glib
import json
from lib import rt
from lib import redmine
from lib.rt import DEFAULT_RT_CATEGORY
from beaker.cache import cache_regions, cache_region

jira_active = True
try:
    from jira.client import JIRA
except:
    jira_active = False

try:
    import evolution
    from evolution import ecal
except:
    evolution = None

# configure regions
cache_regions.update({
    'short_term':{
        'expire': 60,
        'type': 'memory',
        'key_length': 250
    }
})

SOURCE_NONE = ""
SOURCE_GTG = 'gtg'
SOURCE_EVOLUTION = 'evo'
SOURCE_RT = 'rt'
SOURCE_REDMINE = 'redmine'
SOURCE_JIRA = 'jira'
    
class ActivitiesSource(gobject.GObject):
    def __init__(self):
        logging.debug('external init')
        gobject.GObject.__init__(self)
        self.source = conf.get("activities_source")
        self.__gtg_connection = None

        if self.source == SOURCE_EVOLUTION and not evolution:
            self.source == SOURCE_NONE # on failure pretend that there is no evolution
        elif self.source == SOURCE_GTG:
            gobject.GObject.__init__(self)
            dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
        elif self.source == SOURCE_RT:
            self.rt_url = conf.get("rt_url")
            self.rt_user = conf.get("rt_user")
            self.rt_pass = conf.get("rt_pass")
            self.rt_query = conf.get("rt_query")
            self.rt_category = conf.get("rt_category_field")
            if self.rt_url and self.rt_user and self.rt_pass:
                try:
                    self.rt = rt.Rt(self.rt_url, self.rt_user, self.rt_pass)
                    if not self.rt.login():
                        self.source = SOURCE_NONE
                except Exception as e:
                    logging.warn('rt login failed: '+str(e))
                    self.source = SOURCE_NONE
            else:
                self.source = SOURCE_NONE
        elif self.source == SOURCE_REDMINE:
            self.rt_url = conf.get("rt_url")
            self.rt_user = conf.get("rt_user")
            self.rt_pass = conf.get("rt_pass")
            self.rt_category = conf.get("rt_category_field")
            try:
                self.rt_query = json.loads(conf.get("rt_query"))
            except:
                self.rt_query = ({})
            if self.rt_url and self.rt_user and self.rt_pass:
                try:
                    self.redmine = redmine.Redmine(self.rt_url, auth=(self.rt_user,self.rt_pass))
                    if not self.redmine:
                        self.source = SOURCE_NONE
                except:
                    self.source = SOURCE_NONE
            else:
                self.source = SOURCE_NONE
        elif jira_active and self.source == SOURCE_JIRA:
            self.jira_url = conf.get("jira_url")
            self.jira_user = conf.get("jira_user")
            self.jira_pass = conf.get("jira_pass")
            self.jira_query = conf.get("jira_query")
            self.jira_category = conf.get("jira_category_field")
            self.jira_fields=','.join(['summary', self.jira_category])
            if self.jira_url and self.jira_user and self.jira_pass:
                try:
                    options = {'server': self.jira_url}
                    self.jira = JIRA(options, basic_auth = (self.jira_user, self.jira_pass), validate = True)
                except Exception as e:
                    logging.warn('jira connection failed: '+str(e))
                    self.source = SOURCE_NONE
            else:
                self.source = SOURCE_NONE
        
    def get_activities(self, query = None):
        if not self.source:
            return []

        if self.source == SOURCE_EVOLUTION:
            return [activity for activity in get_eds_tasks()
                         if query is None or activity['name'].startswith(query)]
        elif self.source == SOURCE_RT:
            activities = self.__extract_from_rt(query, self.rt_query)
            direct_ticket = None
            if query and re.match("^[0-9]+$", query):
                ticket = self.rt.get_ticket(query)
                if ticket:
                    direct_ticket = self.__extract_activity_from_rt_ticket(ticket)
            if direct_ticket:
                activities.append(direct_ticket)
            if len(activities) <= 2 and not direct_ticket and len(query) > 4:
                li = query.split(' ')
                rt_query = " AND ".join(["(Subject LIKE '%s' OR Owner='%s')" % (q, q) for q in li]) + " AND (Status='new' OR Status='open')"
                #logging.warn(rt_query)
                third_activities = self.__extract_from_rt(query, rt_query, False)
                if activities and third_activities:
                    activities.append({"name": "---------------------", "category": "other open"})
                activities.extend(third_activities)
            return activities
        elif self.source == SOURCE_JIRA:
            activities = self.__extract_from_jira(query, self.jira_query)
            direct_issue = None
            if query and re.match("^[A-Z]+-[0-9]+$", query):
                issue = self.jira.issue(query)
                if issue:
                    direct_issue = self.__extract_activity_from_jira_issue(issue)
            if direct_issue:
                activities.append(direct_issue)
            if len(activities) <= 2 and not direct_issue and len(query) > 4:
                li = query.split(' ')
                jira_query = " AND ".join(["(assignee = '%s' OR summary ~ '%s*')" % (q, q) for q in li]) + " AND resolution = Unresolved order by priority desc, updated desc"
                #logging.warn(rt_query)
                third_activities = self.__extract_from_jira('', jira_query)
                if activities and third_activities:
                    activities.append({"name": "---------------------", "category": "other open"})
                activities.extend(third_activities)
            return activities
        elif self.source == SOURCE_REDMINE:
            activities = self.__extract_from_redmine(query, self.rt_query)
            direct_issue = None
            if query and re.match("^[0-9]+$", query):
                issue = self.redmine.getIssue(query)
                if issue:
                    direct_issue = self.__extract_activity_from_issue(issue)
            if direct_issue:
                activities.append(direct_issue)
            if len(activities) <= 2 and not direct_issue and len(query) > 4:
                rt_query = ({'status_id': 'open', 'subject': query})
                #logging.warn(rt_query)
                third_activities = self.__extract_from_redmine(query, rt_query)
                if activities and third_activities:
                    activities.append({"name": "---------------------", "category": "other open"})
                activities.extend(third_activities)
            return activities
        elif self.source == SOURCE_GTG:
            conn = self.__get_gtg_connection()
            if not conn:
                return []

            activities = []

            tasks = []
            try:
                tasks = conn.GetTasks()
            except dbus.exceptions.DBusException:  #TODO too lame to figure out how to connect to the disconnect signal
                self.__gtg_connection = None
                return self.get_activities(query) # reconnect


            for task in tasks:
                if query is None or task['title'].lower().startswith(query):
                    name = task['title']
                    if len(task['tags']):
                        name = "%s, %s" % (name, " ".join([tag.replace("@", "#") for tag in task['tags']]))

                    activities.append({"name": name, "category": ""})

            return activities
        
    def get_ticket_category(self, activity_id):
        """get activity category depends on source"""
        if not self.source:
            return ""

        if self.source == SOURCE_RT:
            ticket = self.rt.get_ticket(activity_id)
            return self.__extract_cat_from_ticket(ticket)
        elif self.source == SOURCE_JIRA:
            try: 
                issue = self.jira.issue(activity_id)
                return self.__extract_activity_from_jira_issue(issue)
            except Exception as e:
                logging.warn(e)
                return ""
        else:
            return ""
    
    def __extract_activity_from_rt_ticket(self, ticket):
        #activity = {}
        ticket_id = ticket['id']
        #logging.warn(ticket)
        if 'ticket/' in ticket_id:
            ticket_id = ticket_id[7:]
        ticket['name'] = '#'+ticket_id+': '+ticket['Subject'].replace(",", " ")
        if 'Owner' in ticket and ticket['Owner']!=self.rt_user:
            ticket['name'] += " (%s)" % ticket['Owner'] 
        ticket['category'] = self.__extract_cat_from_ticket(ticket)
        ticket['rt_id']=ticket_id;
        return ticket
    
    def __extract_activity_from_issue(self, issue):
        activity = {}
        issue_id = issue.id
        activity['name'] = '#'+str(issue_id)+': '+issue.subject
        activity['rt_id']=issue_id;
        activity['category']="";
        return activity
    
    def __extract_activity_from_jira_issue(self, issue):
        activity = {}
        issue_id = issue.key
        activity['name'] = str(issue_id)+': '+issue.fields.summary
        activity['rt_id'] = issue_id
        if hasattr(issue.fields, self.jira_category):
            activity['category'] = getattr(issue.fields, self.jira_category)
        else:
            activity['category'] = ""
        return activity

    def __extract_from_rt(self, query = None, rt_query = None, checkName = True):
        activities = []
#         results = self.rt.search_simple(rt_query)
        results = self.rt.search_raw(rt_query, [self.rt_category])
        for ticket in results:
            activity = self.__extract_activity_from_rt_ticket(ticket)
            if query is None or not checkName or all(item in activity['name'].lower() for item in query.lower().split(' ')):
                activities.append(activity)
        return activities
        
    def __extract_from_redmine(self, query = None, rt_query = None):
        activities = []
        results = self.redmine.getIssues(rt_query)
        for issue in results:
            activity = self.__extract_activity_from_issue(issue)
            if query is None or all(item in activity['name'].lower() for item in query.lower().split(' ')):
                activities.append(activity)
        return activities
        
    def __extract_from_jira(self, query = None, jira_query = None):
        activities = []
        results = self.__search_jira_issues(jira_query)
        for issue in results:
            activity = self.__extract_activity_from_jira_issue(issue, fields = self.jira_fields)
            if query is None or all(item in activity['name'].lower() for item in query.lower().split(' ')):
                activities.append(activity)
        return activities
    
    @cache_region('short_term', '__extract_from_jira')
    def __search_jira_issues(self, jira_query = None):
        return self.jira.search_issues(jira_query, self.jira_fields, maxResults=100)
        
    def __extract_cat_from_ticket(self, ticket):
        category = DEFAULT_RT_CATEGORY
        if 'Queue' in ticket:
            category = ticket['Queue']
        if self.rt_category in ticket and ticket[self.rt_category]:
            category = ticket[self.rt_category]
#        owner = None
#        if 'Owner' in ticket:
#            owner = ticket['Owner']
#        if owner and owner!=self.rt_user:
#            category += ":"+owner
        return category

    def __get_gtg_connection(self):
        bus = dbus.SessionBus()
        if self.__gtg_connection and bus.name_has_owner("org.gnome.GTG"):
            return self.__gtg_connection

        if bus.name_has_owner("org.gnome.GTG"):
            self.__gtg_connection = dbus.Interface(bus.get_object('org.gnome.GTG', '/org/gnome/GTG'),
                                                   dbus_interface='org.gnome.GTG')
            return self.__gtg_connection
        else:
            return None



def get_eds_tasks():
    try:
        sources = ecal.list_task_sources()
        tasks = []
        if not sources:
            # BUG - http://bugzilla.gnome.org/show_bug.cgi?id=546825
            sources = [('default', 'default')]

        for source in sources:
            category = source[0]

            data = ecal.open_calendar_source(source[1], ecal.CAL_SOURCE_TYPE_TODO)
            if data:
                for task in data.get_all_objects():
                    if task.get_status() in [ecal.ICAL_STATUS_NONE, ecal.ICAL_STATUS_INPROCESS]:
                        tasks.append({'name': task.get_summary(), 'category' : category})
        return tasks
    except Exception, e:
        logging.warn(e)
        return []
