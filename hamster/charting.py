# - coding: utf-8 -

# Copyright (C) 2008 Toms Bauģis <toms.baugis at gmail.com>

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


"""Small charting library that enables you to draw bar and
horizontal bar charts. This library is not intended for scientific graphs.
More like some visual clues to the user.

For graph options see the Chart class and Chart.plot function

Author: toms.baugis@gmail.com
Feel free to contribute - more info at Project Hamster web page:
http://projecthamster.wordpress.com/

Example:
    # create new chart object
    chart = Chart(max_bar_width = 40) 
    
    eventBox = gtk.EventBox() # charts go into eventboxes, or windows
    place = self.get_widget("totals_by_day") #just some placeholder

    eventBox.add(chart);
    place.add(eventBox)

    #Let's imagine that we count how many apples we have gathered, by day
    data = [["Mon", 20], ["Tue", 12], ["Wed", 80],
            ["Thu", 60], ["Fri", 40], ["Sat", 0], ["Sun", 0]]
    self.day_chart.plot(data)

"""

import gtk
import gobject
import cairo, pango
import copy
import math
from sys import maxint

# Tango colors
light = [(252, 233, 79), (252, 175, 62),  (233, 185, 110),
         (138, 226, 52), (114, 159, 207), (173, 127, 168), 
         (239, 41,  41), (238, 238, 236), (136, 138, 133)]

medium = [(237, 212, 0),  (245, 121, 0),   (193, 125, 17),
          (115, 210, 22), (52,  101, 164), (117, 80,  123), 
          (204, 0,   0),  (211, 215, 207), (85, 87, 83)]

dark = [(196, 160, 0), (206, 92, 0),    (143, 89, 2),
        (78, 154, 6),  (32, 74, 135),   (92, 53, 102), 
        (164, 0, 0),   (186, 189, 182), (46, 52, 54)]

color_count = len(light)

def set_color(context, color, g = None, b = None):
    if g and b:
        r,g,b = color / 255.0, g / 255.0, b / 255.0
    else:
        r,g,b = color[0] / 255.0, color[1] / 255.0, color[2] / 255.0
    context.set_source_rgb(r, g, b)
    

def set_color_gdk(context, color):
    # set_color_gdk(context, self.style.fg[gtk.STATE_NORMAL]);
    r,g,b = color.red / 65536.0, color.green / 65536.0, color.blue / 65536.0
    context.set_source_rgb(r, g, b)
    
class Integrator(object):
    """an iterator, inspired by "visualizing data" book to simplify animation"""
    def __init__(self, start_value, precision = 0, frames = 50):
        """precision determines, until which decimal number we go"""
        self.value = start_value
        self.target_value = start_value
        self.frames = float(frames)
        self.current_frame = 0
        
    def __repr__(self):
        return "<Integrator %s, %s>" % (self.value, self.target_value)
        
    def target(self, value):
        """target next value"""
        self.current_frame = 0
        self.target_value = value
        
    def update(self):
        """goes from current to target value
        if there is any action needed. returns false when done"""
        moving = self.current_frame < self.frames
        if moving:
            self.current_frame +=1
            self.value = self._smoothstep(self.current_frame / self.frames,
                                          self.value, self.target_value)
        return (round(self.value,4) - round(self.target_value,4) != 0) and moving

    def finish(self):
        self.current_frame = 0.0
        self.value = self.target_value

    def _smoothstep(self, v, start, end):
        smooth = 1 - (1 - v)
        return (end * smooth) + (start * (1-smooth))
        

def size_list(set, target_set):
    """turns set lenghts into target set - trim it, stretches it, but
       keeps values for cases when lengths match
    """
    set = set[:min(len(set), len(target_set))] #shrink to target
    set += target_set[len(set):] #grow to target

    #nest
    for i in range(len(set)):
        if type(set[i]) == list:
            set[i] = size_list(set[i], target_set[i])
    return set

def get_limits(set, stack_subfactors = True):
    # stack_subfactors indicates whether we should sum up nested lists
    max_value, min_value = -maxint, maxint
    for col in set:
        if type(col) in [int, float]:
            max_value = max(col, max_value)
            min_value = min(col, min_value)
        elif stack_subfactors:
            max_value = max(sum(col), max_value)
            min_value = min(sum(col), min_value)
        else:
            for row in col:
                max_value = max(row, max_value)
                min_value = max(row, min_value)

    return min_value, max_value
    

class Chart(gtk.DrawingArea):
    """Chart constructor. Optional arguments:
        orient_vertical = [True|False] - Chart orientation.
                                         Defaults to vertical
        max_bar_width = pixels - Maximal width of bar. If not specified,
                                 bars will stretch to fill whole area
        values_on_bars = [True|False] - Should bar values displayed on each bar.
                                        Defaults to False
        stretch_grid = [True|False] - Should the grid be of fixed or flex
                                      size. If set to true, graph will be split
                                      in 4 parts, which will stretch on resize.
                                      Defaults to False.
        animate = [True|False] - Should the bars grow/shrink on redrawing.
                                 Animation happens only if labels and their
                                 order match.
                                 Defaults to True.
        legend_width = pixels - Legend width in pixels. Will keep you graph
                                from floating horizontally

        Then there are some defaults, you can override:
        default_grid_stride - If stretch_grid is set to false, this allows you
                              to choose granularity of grid. Defaults to 50
        animation_frames - in how many steps should the animation be done
        animation_timeout - after how many miliseconds should we draw next frame
    """
    def __init__(self, **args):
        gtk.DrawingArea.__init__(self)
        self.connect("expose_event", self._expose)

        """now let's see what we have in args!"""
        self.orient_vertical = "orient" not in args or args["orient"] == "vertical" # defaults to true

        self.max_bar_width = args.get("max_bar_width", 0)

        self.values_on_bars = "values_on_bars" in args and args["values_on_bars"] #defaults to false

        self.stretch_grid = "stretch_grid" in args and args["stretch_grid"] #defaults to false

        self.animate = "animate" not in args or args["animate"] # defaults to true

        self.show_scale = "show_scale" not in args or args["show_scale"] # defaults to true
        
        self.background = args.get("background", None)
        self.chart_background = args.get("chart_background", None)
        self.bar_base_color = args.get("bar_base_color", None)
        
        self.bars_beveled = "bars_beveled" not in args or args["bars_beveled"] # defaults to true
        
        
        self.legend_width = args.get("legend_width", 0)
        
        self.show_total = "show_total" in args and args["show_total"] #defaults to false
        
        self.labels_at_end = "labels_at_end" in args and args["labels_at_end"] #defaults to false

        #and some defaults
        self.default_grid_stride = 50
        
        self.animation_frames = 50
        self.animation_timeout = 16 #in miliseconds, targetting 60fps

        self.current_frame = self.animation_frames
        self.freeze_animation = False
        
        self.value_format = args.get("value_format", "%s")
        
        self.show_series = "show_series" not in args or args["show_series"] # defaults to true
        
        self.grid_stride = args.get("grid_stride", None)
        

        self.current_max = None
        self.integrators = []
        self.moving = False
        
    def _expose(self, widget, event):
        """expose is when drawing's going on, like on _invalidate"""
        self.context = widget.window.cairo_create()
        self.context.rectangle(event.area.x, event.area.y, event.area.width, event.area.height)
        self.context.clip()

        self.layout = self.context.create_layout()
        self.layout.set_font_description(pango.FontDescription("Sans 8"))
        
        alloc = self.get_allocation()  #x, y, width, height
        self.width, self.height = alloc[2], alloc[3]


        # fill whole area 
        if self.background:
            self.context.rectangle(0, 0, self.width, self.height)
            self.context.set_source_rgb(*self.background)
            self.context.fill_preserve()
            self.context.stroke()
        
        #forward to specific implementations
        self._draw()

        return False


    def plot(self, keys, data, stack_keys = None):
        """Draw chart with given data"""
        self.keys, self.data, self.stack_keys = keys, data, stack_keys

        self.show()

        if not data: #if there is no data, let's just draw blank
            self._invalidate()
            return


        #if we are moving, freeze for moment until we recalculate things
        self.freeze_animation = self.moving


        min, self.max_value = get_limits(data)

        if not self.current_max:
            self.current_max = Integrator(0)
        else:
            self.current_max.target(self.max_value)
        
        self._redo_factors()
        
        if self.animate:
            #resume or call replot!
            if self.freeze_animation:
                self.freeze_animation = False
            else:
                gobject.timeout_add(self.animation_timeout, self._replot)
        else:
            def finish_all(integrators):
                for i in range(len(integrators)):
                    if type(integrators[i]) == list:
                        finish_all(integrators[i])
                    else:
                        integrators[i].finish()
    
            finish_all(self.integrators)


            self._invalidate()
            

        
    def _smoothstep(self, v, start, end):
        smooth = 1 - (1 - v) * (1 - v)
        return (end * smooth) + (start * (1-smooth))
        
    def _redo_factors(self):
        # calculates new factors and then updates existing set
        max_value = float(self.max_value) or 1 # avoid division by zero
        
        self.integrators = size_list(self.integrators, self.data)

        #need function to go recursive
        def retarget(integrators, new_values):
            for i in range(len(new_values)):
                if type(new_values[i]) == list:
                    integrators[i] = retarget(integrators[i], new_values[i])
                else:
                    if isinstance(integrators[i], Integrator) == False:
                        integrators[i] = Integrator(0, 1) #8 numbers after comma :)

                    integrators[i].target(new_values[i] / max_value)
            
            return integrators
    
        retarget(self.integrators, self.data)
    



    def _replot(self):
        """Internal function to do the math, going from previous set to the
           new one, and redraw graph"""
        if self.freeze_animation:
            return True #just wait until they release us!

        #this can get called before expose    
        if not self.window:
            self._invalidate()
            return False

        #ok, now we are good!
        self.current_max.update()


        def update_all(integrators):
            still_moving = False
            for z in range(len(integrators)):
                if type(integrators[z]) == list:
                    still_moving = update_all(integrators[z]) or still_moving
                else:
                    still_moving = integrators[z].update() or still_moving
            return still_moving

        self.moving = update_all(self.integrators)

        self._invalidate()
        
        return self.moving #return if there is still work to do

    def _invalidate(self):
        """Force redrawal of chart"""
        if self.window:    #this can get called before expose    
            alloc = self.get_allocation()
            rect = gtk.gdk.Rectangle(alloc.x, alloc.y, alloc.width, alloc.height)
            self.window.invalidate_rect(rect, True)
            self.window.process_updates(True)

    def _fill_area(self, x, y, w, h, color):
        self.context.rectangle(x, y, w, h)
        self.context.set_source_rgb(*[c / 256.0 for c in color])
        self.context.fill_preserve()
        self.context.stroke()

    def _draw_bar(self, x, y, w, h, color = None):
        """ draws a nice bar"""
        context = self.context
        
        base_color = color or self.bar_base_color or (220, 220, 220)

        if self.bars_beveled:
            self._fill_area(x, y, w, h,
                            [b - 30 for b in base_color])

            if w > 2 and h > 2:
                self._fill_area(x + 1, y + 1, w - 2, h - 2,
                                [b + 20 for b in base_color])
    
            if w > 3 and h > 3:
                self._fill_area(x + 2, y + 2, w - 4, h - 4, base_color)
        else:
            self._fill_area(x, y, w, h, base_color)

    

    def _longest_label(self, labels):
        max_extent = 0
        for label in labels:
            self.layout.set_text(label)
            label_w, label_h = self.layout.get_pixel_size()
            max_extent = max(label_w + 5, max_extent)
        
        return max_extent

    def draw(self):
        print "OMG OMG, not implemented!!!"


class BarChart(Chart):
    def _draw_moving_parts(self):
        graph_x, graph_y, graph_width, graph_height = self.graph_x, self.graph_y, self.graph_width, self.graph_height
        context = self.context
        keys, rowcount = self.keys, len(self.keys)

        legend_width = self.legend_width or self._longest_label(keys)

        max_bar_size = graph_height
        #make sure bars don't hit the ceiling
        if self.animate:
            max_bar_size = graph_height - 10


        context.set_antialias(cairo.ANTIALIAS_NONE)
        
        """draw moving parts"""
        #flip the matrix vertically, so we do not have to think upside-down
        context.save()
        context.set_line_width(0)
        context.transform(cairo.Matrix(yy = -1, y0 = graph_height))

        # bars themselves
        for i in range(rowcount):
            color = 3

            bar_start = 0
            
            base_color = self.bar_base_color or (220, 220, 220)

            gap = self.bar_width * 0.05
            bar_x = graph_x + (self.bar_width * i) + gap

            for j in range(len(self.integrators[i])):
                factor = self.integrators[i][j].value

                if factor > 0:
                    bar_size = max_bar_size * factor
                    
                    self._draw_bar(bar_x,
                                   bar_start,
                                   self.bar_width - (gap * 2),
                                   bar_size,
                                   [col - (j * 22) for col in base_color])
    
                    bar_start += bar_size
                color +=1
                if color > 2:
                    color = 0


        context.restore()
        #flip the matrix back, so text doesn't come upside down
        context.transform(cairo.Matrix(yy = 1, y0 = graph_height))

        context.save()
        
        self.layout.set_width(-1)

        #white grid and scale values
        if self.grid_stride and self.max_value:
            # if grid stride is less than 1 then we consider it to be percentage
            if self.grid_stride < 1:
                grid_stride = int(self.max_value * self.grid_stride)
            else:
                grid_stride = int(self.grid_stride)
            
            context.set_line_width(1)
            for i in range(grid_stride, int(self.max_value), grid_stride):
                y = - max_bar_size * (i / self.max_value)
                label = str(i)

                self.layout.set_text(label)
                label_w, label_h = self.layout.get_pixel_size()

                context.move_to(legend_width - label_w, y - label_h / 2)
                set_color(context, medium[8])
                context.show_layout(self.layout)
                context.stroke()

                set_color(context, (255,255,255))
                context.move_to(graph_x, y)
                context.line_to(graph_x + graph_width, y)
                context.stroke()
            

        context.restore()

        context.set_antialias(cairo.ANTIALIAS_DEFAULT)

        #series keys
        if self.show_series:
            #put series keys
            set_color(context, dark[8]);
            
            y = 0
            label_y = None

            # if labels are at end, then we need show them for the last bar! 
            if self.labels_at_end:
                factors = self.integrators[0]
            else:
                factors = self.integrators[-1]

            self.layout.set_ellipsize(pango.ELLIPSIZE_END)
            self.layout.set_width(legend_width * 1000)
            if self.labels_at_end:
                self.layout.set_alignment(pango.ALIGN_LEFT)
            else:
                self.layout.set_alignment(pango.ALIGN_RIGHT)
    
            for j in range(len(factors)):
                factor = factors[j].value
                bar_size = factor * max_bar_size
                
                if round(bar_size) > 0:
                    label = "%s" % self.stack_keys[j]
                    
                    
                    self.layout.set_text(label)
                    label_w, label_h = self.layout.get_pixel_size()
                    
                    y -= bar_size
                    intended_position = round(y + (bar_size - label_h) / 2)
                    
                    if label_y:
                        label_y = min(intended_position, label_y - label_h)
                    else:
                        label_y = intended_position
                    
                    if self.labels_at_end:
                        label_x = graph_x + graph_width 
                        line_x1 = graph_x + graph_width - 1
                        line_x2 = graph_x + graph_width - 6
                    else:
                        label_x = 0
                        line_x1 = legend_width + 2
                        line_x2 = legend_width + 8


                    context.move_to(label_x, label_y)
                    context.show_layout(self.layout)

                    if label_y != intended_position:
                        context.move_to(line_x1, label_y + label_h / 2)
                        context.line_to(line_x2, round(y + bar_size / 2))

                    
                    
            context.stroke()        



    
    def _draw(self):
        context = self.context
        
        rowcount, keys = len(self.keys), self.keys

        # graph box dimensions
        legend_width = self.legend_width or self._longest_label(keys)

        if self.show_scale:
            legend_width = max(self.legend_width, 20)
        
        if self.stack_keys and self.labels_at_end:
            graph_x = 0
            graph_width = self.width - max(legend_width, self._longest_label(self.stack_keys))
        else:
            graph_x = legend_width + 8 # give some space to scale labels
            graph_width = self.width - graph_x - 10

        graph_y = 0
        graph_height = self.height - 15

        self.graph_x, self.graph_y, self.graph_width, self.graph_height = graph_x, graph_y, graph_width, graph_height

        context.set_line_width(1)
        
        if self.chart_background:
            self._fill_area(graph_x - 1, graph_y, graph_width, graph_height,
                            self.chart_background)


        self.bar_width = min(graph_width / float(rowcount), self.max_bar_width)


        # keys
        prev_end = None
        set_color(context, dark[8]);
        self.layout.set_width(-1)

        for i in range(len(keys)):
            self.layout.set_text(keys[i])
            label_w, label_h = self.layout.get_pixel_size()

            intended_x = graph_x + (self.bar_width * i) + (self.bar_width - label_w) / 2.0
            
            if not prev_end or intended_x > prev_end:
                context.move_to(intended_x, graph_y + graph_height + 4)
                context.show_layout(self.layout)
            
                prev_end = intended_x + label_w + 10
                
        context.stroke()
                

        # maximal
        if self.show_total:
            max_label = "%d" % self.max_value

            self.layout.set_text(max_label)
            label_w, label_h = self.layout.get_pixel_size()

            context.move_to(graph_x - label_w - 16, 10)
            context.show_layout(self.layout)
            
            context.stroke()

        self._draw_moving_parts()







class HorizontalBarChart(Chart):
    def _draw(self):
        rowcount, keys = len(self.keys), self.keys
        
        context = self.context
        
        #push graph to the right, so it doesn't overlap, and add little padding aswell
        legend_width = self.legend_width or self._longest_label(keys)

        graph_x = legend_width
        graph_x += 8 #add another 8 pixes of padding
        
        graph_width = self.width - graph_x
        graph_y, graph_height = 0, self.height


        if self.chart_background:
            self._fill_area(graph_x, graph_y, graph_width, graph_height, self.chart_background)
        

        """
        # stripes for the case i decided that they are not annoying
        for i in range(0, round(self.current_max.value), 10):
            x = graph_x + (graph_width * (i / float(self.current_max.value)))
            w = (graph_width * (5 / float(self.current_max.value)))

            context.set_source_rgb(0.90, 0.90, 0.90)
            context.rectangle(x + w, graph_y, w, graph_height)
            context.fill_preserve()
            context.stroke()
            
            context.set_source_rgb(0.70, 0.70, 0.70)
            context.move_to(x, graph_y + graph_height - 2)

            context.show_text(str(i))
        """    
    
        if not self.data:  #if we have nothing, let's go home
            return

        
        bar_width = int(graph_height / float(rowcount))
        if self.max_bar_width:
            bar_width = min(bar_width, self.max_bar_width)

        
        max_bar_size = graph_width - 15
        gap = bar_width * 0.05


        self.layout.set_alignment(pango.ALIGN_RIGHT)
        self.layout.set_ellipsize(pango.ELLIPSIZE_END)
        
        self.layout.set_width(legend_width * 1000)

        # keys
        set_color(context, dark[8])        
        for i in range(rowcount):
            label = keys[i]
            
            self.layout.set_text(label)
            label_w, label_h = self.layout.get_pixel_size()

            context.move_to(0, (bar_width * i) + (bar_width - label_h) / 2)
            context.show_layout(self.layout)
        context.stroke()

        
        
        context.set_line_width(1)
        

        
        context.set_line_width(0)
        context.set_antialias(cairo.ANTIALIAS_NONE)


        # bars themselves
        for i in range(rowcount):
            bar_start = 0
            base_color = self.bar_base_color or (220, 220, 220)

            gap = bar_width * 0.05

            bar_y = graph_y + (bar_width * i) + gap

            for j in range(len(self.integrators[i])):
                factor = self.integrators[i][j].value
                if factor > 0:
                    bar_size = max_bar_size * factor
                    bar_height = bar_width - (gap * 2)
                    
                    self._draw_bar(graph_x,
                                   bar_y,
                                   bar_size,
                                   bar_height,
                                   [col - (j * 22) for col in base_color])
    
                    bar_start += bar_size


        #values

        self.layout.set_width(-1)
        context.set_antialias(cairo.ANTIALIAS_DEFAULT)
        set_color(context, dark[8])        


        if self.values_on_bars:
            for i in range(rowcount):
                label = self.value_format % sum(self.data[i])
                factor = sum([integrator.value for integrator in self.integrators[i]])

                self.layout.set_text(label)
                label_w, label_h = self.layout.get_pixel_size()

                bar_size = max_bar_size * factor
                vertical_padding = (bar_width + label_h) / 2.0 - label_h
                
                if  bar_size - vertical_padding < label_w:
                    label_x = graph_x + bar_size + vertical_padding
                else:
                    label_x = graph_x + bar_size - label_w - vertical_padding
                
                context.move_to(label_x, graph_y + (bar_width * i) + (bar_width - label_h) / 2.0)
                context.show_layout(self.layout)
        else:
            # show max value
            context.move_to(graph_x + graph_width - 30, graph_y + 10)
            max_label = self.value_format % self.current_max.value
            self.layout.set_text(max_label)
            context.show_layout(self.layout)


