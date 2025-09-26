from kivy.clock import Clock
from kivy.compat import string_types
from kivy.properties import StringProperty, ObjectProperty, NumericProperty, BooleanProperty
from kivy.uix.spinner import Spinner
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.boxlayout import BoxLayout
from kivy.core.window import Window
from kivy.factory import Factory
from kivy.uix.dropdown import DropDown
from kivy.uix.textinput import TextInput
from kivy.uix.switch import Switch
from kivy.uix.popup import Popup
from kivy.uix.modalview import ModalView
import sys

class Tooltip(BoxLayout):
    pass

class ToolTipLabel(Label):
    min_width = 200

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.text_size = (max(self.width, self.min_width), None)

    def on_size(self, *args):
        self.text_size = (max(self.width, self.min_width), None)
        self.texture_update()



class ToolTipSwitch(Switch):
    tooltip_txt = StringProperty('')
    tooltip_cls = ObjectProperty(Tooltip)
    tooltip_image = StringProperty('')
    tooltip_delay = NumericProperty(0.5)
    show_tooltips = BooleanProperty(False)
    tooltip_image_size = ObjectProperty(None)

    def __init__(self, **kwargs):
        self._tooltip = None
        super(ToolTipSwitch, self).__init__(**kwargs)
        # On iOS, tooltips are not supported, so we disable them
        if sys.platform == 'ios':
            return
        fbind = self.fbind
        fbind('tooltip_cls', self._build_tooltip)
        fbind('tooltip_txt', self._update_tooltip)
        fbind('tooltip_image', self._update_image)
        fbind('tooltip_image_size', self._update_image_size)
        Window.bind(mouse_pos=self.on_mouse_pos)
        self.bind(on_release=self.close_tooltip)
        self._build_tooltip()
        

    def _is_blocked_by_modal(self):
        for child in Window.children:
            if isinstance(child, (Popup, ModalView)):
                try:
                    current = self.parent
                    depth = 0
                    while current and depth < 20:
                        if current == child:
                            return False
                        current = current.parent
                        depth += 1
                    return True
                except:
                    return True
        return False
    
    def _build_tooltip(self, *largs):
        # Only build the tooltip if it hasn't been created yet
        if self._tooltip:
            return

        cls = self.tooltip_cls
        if isinstance(cls, string_types):
            cls = Factory.get(cls)
        self._tooltip = cls()

        image_widget = self._tooltip.ids.tooltip_image
        image_widget.bind(texture_size=self._update_image_size)
        self._update_image()
        self._update_tooltip()

    def _update_tooltip(self, *largs):
        txt = self.tooltip_txt
        if txt:
            self._tooltip.ids.tooltip_label.text = txt
            self._tooltip.ids.tooltip_label.size = self._tooltip.ids.tooltip_label.texture_size
        else:
            self._tooltip.ids.tooltip_label.text = ''
            self._tooltip.ids.tooltip_label.size = (0, 0)
        
        self._update_tooltip_size()
    
    def _update_image(self, *largs):
        imgpath = self.tooltip_image
        if imgpath:
            self._tooltip.ids.tooltip_image.source = imgpath
            self._tooltip.ids.tooltip_image.visible = True
        else:
            self._tooltip.ids.tooltip_image.source = ''
            self._tooltip.ids.tooltip_image.size = (0, 0)
            self._tooltip.ids.tooltip_image.visible = False

    def _update_image_size(self, instance, value):
        if self.tooltip_image_size:
            self._tooltip.ids.tooltip_image.size = self.tooltip_image_size
        else:
            instance.size = instance.texture_size[0], instance.texture_size[1]

    def _update_tooltip_size(self):
        tooltip_label = self._tooltip.ids.tooltip_label
        tooltip_image = self._tooltip.ids.tooltip_image

        # Calculate new size based on text and image dimensions
        text_width, text_height = tooltip_label.texture_size
        image_width, image_height = tooltip_image.size

        new_width = max(text_width + 20, image_width + 20)
        new_height = text_height + image_height + 20

        # Update tooltip size
        self._tooltip.size = (new_width, new_height)
        self._tooltip.canvas.ask_update()  # Force UI refresh
        self._tooltip.ids.tooltip_label.texture_update()

    def on_mouse_pos(self, *args):
        if not self.show_tooltips:
            self.close_tooltip()
            return
        
        if not self.get_root_window():
            self.close_tooltip()
            return
        
        if not self.tooltip_txt and not self.tooltip_image:
            self.close_tooltip()
            return
        
        if self.disabled:
            self.close_tooltip()
            return
        
        if self._is_blocked_by_modal():
            self.close_tooltip()
            return
        
    
        pos = args[1]
        tooltip_width, tooltip_height = self._tooltip.size
        window_width, window_height = Window.size
        tooltip_label = self._tooltip.ids.tooltip_label
        tooltip_image = self._tooltip.ids.tooltip_image

        text_width = tooltip_label.texture_size[0]
        image_width = tooltip_image.width

        tooltip_padding = 10
        if self.tooltip_image:
            tooltip_padding = 40

        tooltip_width = max(text_width, image_width)
        tooltip_height = tooltip_label.texture_size[1] + tooltip_image.height + tooltip_padding
        self._tooltip.size = (tooltip_width, tooltip_height)
        x = pos[0]
        y = pos[1]
        if x + tooltip_width > window_width:
            x = window_width - tooltip_width - 30

        # Adjust vertical position if too close to the bottom edge
        if y + tooltip_height > window_height - 30:
            y = window_height - tooltip_height - 40
        self._tooltip.pos = (x, y)

        Clock.unschedule(self.display_tooltip) 
        self.close_tooltip() 
        if self.collide_point(*self.to_widget(*pos)):
            Clock.schedule_once(self.display_tooltip, self.tooltip_delay)




    def close_tooltip(self, *args):
        if self._tooltip: #for memory leaks
            Window.remove_widget(self._tooltip)

    def display_tooltip(self, *args):
        Window.add_widget(self._tooltip)


class ToolTipTextInput(TextInput):
    tooltip_txt = StringProperty('')
    tooltip_cls = ObjectProperty(Tooltip)
    tooltip_image = StringProperty('')
    tooltip_delay = NumericProperty(0.5)
    show_tooltips = BooleanProperty(False)
    tooltip_image_size = ObjectProperty(None)

    def __init__(self, **kwargs):
        self._tooltip = None
        super(ToolTipTextInput, self).__init__(**kwargs)
        # On iOS, tooltips are not supported, so we disable them
        if sys.platform == 'ios':
            return
        fbind = self.fbind
        fbind('tooltip_cls', self._build_tooltip)
        fbind('tooltip_txt', self._update_tooltip)
        fbind('tooltip_image', self._update_image)
        fbind('tooltip_image_size', self._update_image_size)
        Window.bind(mouse_pos=self.on_mouse_pos)
        self.bind(on_release=self.close_tooltip)
        self._build_tooltip()
        
    def _is_blocked_by_modal(self):
        for child in Window.children:
            if isinstance(child, (Popup, ModalView)):
                try:
                    current = self.parent
                    depth = 0
                    while current and depth < 20:
                        if current == child:
                            return False
                        current = current.parent
                        depth += 1
                    return True
                except:
                    return True
        return False

    def _build_tooltip(self, *largs):
        # Only build the tooltip if it hasn't been created yet
        if self._tooltip:
            return

        cls = self.tooltip_cls
        if isinstance(cls, string_types):
            cls = Factory.get(cls)
        self._tooltip = cls()

        image_widget = self._tooltip.ids.tooltip_image
        image_widget.bind(texture_size=self._update_image_size)
        self._update_image()
        self._update_tooltip()

    def _update_tooltip(self, *largs):
        txt = self.tooltip_txt
        if txt:
            self._tooltip.ids.tooltip_label.text = txt
            self._tooltip.ids.tooltip_label.size = self._tooltip.ids.tooltip_label.texture_size
        else:
            self._tooltip.ids.tooltip_label.text = ''
            self._tooltip.ids.tooltip_label.size = (0, 0)
        
        self._update_tooltip_size()
    
    def _update_image(self, *largs):
        imgpath = self.tooltip_image
        if imgpath:
            self._tooltip.ids.tooltip_image.source = imgpath
            self._tooltip.ids.tooltip_image.visible = True
        else:
            self._tooltip.ids.tooltip_image.source = ''
            self._tooltip.ids.tooltip_image.size = (0, 0)
            self._tooltip.ids.tooltip_image.visible = False

    def _update_image_size(self, instance, value):
        if self.tooltip_image_size:
            self._tooltip.ids.tooltip_image.size = self.tooltip_image_size
        else:
            instance.size = instance.texture_size[0], instance.texture_size[1]

    def _update_tooltip_size(self):
        tooltip_label = self._tooltip.ids.tooltip_label
        tooltip_image = self._tooltip.ids.tooltip_image

        # Calculate new size based on text and image dimensions
        text_width, text_height = tooltip_label.texture_size
        image_width, image_height = tooltip_image.size

        new_width = max(text_width + 20, image_width + 20)
        new_height = text_height + image_height + 20

        # Update tooltip size
        self._tooltip.size = (new_width, new_height)
        self._tooltip.canvas.ask_update()  # Force UI refresh
        self._tooltip.ids.tooltip_label.texture_update()

    def on_mouse_pos(self, *args):
        if not self.show_tooltips:
            self.close_tooltip()
            return
        
        if not self.get_root_window():
            self.close_tooltip()
            return
        
        if not self.tooltip_txt and not self.tooltip_image:
            self.close_tooltip()
            return
        
        if self.disabled:
            self.close_tooltip()
            return
        
        if self._is_blocked_by_modal():
            self.close_tooltip()
            return
        
    
        pos = args[1]
        tooltip_width, tooltip_height = self._tooltip.size
        window_width, window_height = Window.size
        tooltip_label = self._tooltip.ids.tooltip_label
        tooltip_image = self._tooltip.ids.tooltip_image

        text_width = tooltip_label.texture_size[0]
        image_width = tooltip_image.width

        tooltip_padding = 10
        if self.tooltip_image:
            tooltip_padding = 40

        tooltip_width = max(text_width, image_width)
        tooltip_height = tooltip_label.texture_size[1] + tooltip_image.height + tooltip_padding
        self._tooltip.size = (tooltip_width, tooltip_height)
        x = pos[0]
        y = pos[1]
        if x + tooltip_width > window_width:
            x = window_width - tooltip_width - 30

        # Adjust vertical position if too close to the bottom edge
        if y + tooltip_height > window_height - 30:
            y = window_height - tooltip_height - 40
        self._tooltip.pos = (x, y)

        Clock.unschedule(self.display_tooltip) 
        self.close_tooltip() 
        if self.collide_point(*self.to_widget(*pos)):
            Clock.schedule_once(self.display_tooltip, self.tooltip_delay)




    def close_tooltip(self, *args):
        if self._tooltip: #for memory leaks
            Window.remove_widget(self._tooltip)

    def display_tooltip(self, *args):
        Window.add_widget(self._tooltip)

class ToolTipButton(Button):
    tooltip_txt = StringProperty('')
    tooltip_cls = ObjectProperty(Tooltip)
    tooltip_image = StringProperty('')
    tooltip_delay = NumericProperty(0.5)
    show_tooltips = BooleanProperty(False)
    tooltip_image_size = ObjectProperty(None)
    tooltip_radius = NumericProperty(0.2)

    def __init__(self, **kwargs):
        self._tooltip = None
        super(ToolTipButton, self).__init__(**kwargs)
        # On iOS, tooltips are not supported, so we disable them
        if sys.platform == 'ios':
            return
        fbind = self.fbind
        fbind('tooltip_cls', self._build_tooltip)
        fbind('tooltip_txt', self._update_tooltip)
        fbind('tooltip_image', self._update_image)
        fbind('tooltip_image_size', self._update_image_size)
        Window.bind(mouse_pos=self.on_mouse_pos)
        self.bind(on_release=self.close_tooltip)
        self._build_tooltip()
        
    def _is_blocked_by_modal(self):
        for child in Window.children:
            if isinstance(child, (Popup, ModalView)):
                try:
                    current = self.parent
                    depth = 0
                    while current and depth < 20:
                        if current == child:
                            return False
                        current = current.parent
                        depth += 1
                    return True
                except:
                    return True
        return False

    def _build_tooltip(self, *largs):
        # Only build the tooltip if it hasn't been created yet
        if self._tooltip:
            return

        cls = self.tooltip_cls
        if isinstance(cls, string_types):
            cls = Factory.get(cls)
        self._tooltip = cls()

        image_widget = self._tooltip.ids.tooltip_image
        image_widget.bind(texture_size=self._update_image_size)
        self._update_image()
        self._update_tooltip()

    def _update_tooltip(self, *largs):
        txt = self.tooltip_txt
        if txt:
            self._tooltip.ids.tooltip_label.text = txt
            self._tooltip.ids.tooltip_label.size = self._tooltip.ids.tooltip_label.texture_size
        else:
            self._tooltip.ids.tooltip_label.text = ''
            self._tooltip.ids.tooltip_label.size = (0, 0)
        
        self._update_tooltip_size()
    
    def _update_image(self, *largs):
        imgpath = self.tooltip_image
        if imgpath:
            self._tooltip.ids.tooltip_image.source = imgpath
            self._tooltip.ids.tooltip_image.visible = True
        else:
            self._tooltip.ids.tooltip_image.source = ''
            self._tooltip.ids.tooltip_image.size = (0, 0)
            self._tooltip.ids.tooltip_image.visible = False

    def _update_image_size(self, instance, value):
        if self.tooltip_image_size:
            self._tooltip.ids.tooltip_image.size = self.tooltip_image_size
        else:
            instance.size = instance.texture_size[0], instance.texture_size[1]

    def _update_tooltip_size(self):
        tooltip_label = self._tooltip.ids.tooltip_label
        tooltip_image = self._tooltip.ids.tooltip_image

        # Calculate new size based on text and image dimensions
        text_width, text_height = tooltip_label.texture_size
        image_width, image_height = tooltip_image.size

        new_width = max(text_width + 20, image_width + 20)
        new_height = text_height + image_height + 20

        # Update tooltip size
        self._tooltip.size = (new_width, new_height)
        self._tooltip.canvas.ask_update()  # Force UI refresh
        self._tooltip.ids.tooltip_label.texture_update()

    def on_mouse_pos(self, *args):
        if not self.show_tooltips:
            self.close_tooltip()
            return
        
        if not self.get_root_window():
            self.close_tooltip()
            return
        
        if not self.tooltip_txt and not self.tooltip_image:
            self.close_tooltip()
            return
        
        if self.disabled:
            self.close_tooltip()
            return
        
        if self._is_blocked_by_modal():
            self.close_tooltip()
            return
    
        pos = args[1]
        tooltip_width, tooltip_height = self._tooltip.size
        window_width, window_height = Window.size
        tooltip_label = self._tooltip.ids.tooltip_label
        tooltip_image = self._tooltip.ids.tooltip_image

        text_width = tooltip_label.texture_size[0]
        image_width = tooltip_image.width

        tooltip_padding = 10
        if self.tooltip_image:
            tooltip_padding = 40

        tooltip_width = max(text_width, image_width)
        tooltip_height = tooltip_label.texture_size[1] + tooltip_image.height + tooltip_padding
        self._tooltip.size = (tooltip_width, tooltip_height)
        x = pos[0]
        y = pos[1]
        if x + tooltip_width > window_width:
            x = window_width - tooltip_width - 30

        # Adjust vertical position if too close to the bottom edge
        if y + tooltip_height > window_height - 30:
            y = window_height - tooltip_height - 40
        self._tooltip.pos = (x, y)

        Clock.unschedule(self.display_tooltip) 
        self.close_tooltip() 
        if self.collide_point(*self.to_widget(*pos)):
            Clock.schedule_once(self.display_tooltip, self.tooltip_delay)

    def close_tooltip(self, *args):
        if self._tooltip: #for memory leaks
            Window.remove_widget(self._tooltip)

    def display_tooltip(self, *args):
        Window.add_widget(self._tooltip)


class ToolTipDropDown(DropDown):
    tooltip_txt = StringProperty('')
    tooltip_cls = ObjectProperty(Tooltip)
    tooltip_image = StringProperty('')
    tooltip_delay = NumericProperty(0.5)
    show_tooltips = BooleanProperty(False)
    tooltip_image_size = ObjectProperty(None)

    def __init__(self, **kwargs):
        self._tooltip = None
        super(ToolTipDropDown, self).__init__(**kwargs)
        # On iOS, tooltips are not supported, so we disable them
        if sys.platform == 'ios':
            return
        fbind = self.fbind
        fbind('tooltip_cls', self._build_tooltip)
        fbind('tooltip_txt', self._update_tooltip)
        fbind('tooltip_image', self._update_image)
        fbind('tooltip_image_size', self._update_image_size)
        Window.bind(mouse_pos=self.on_mouse_pos)
        self.bind(on_release=self.close_tooltip)
        self._build_tooltip()
        
    def _is_blocked_by_modal(self):
        for child in Window.children:
            if isinstance(child, (Popup, ModalView)):
                try:
                    current = self.parent
                    depth = 0
                    while current and depth < 20:
                        if current == child:
                            return False
                        current = current.parent
                        depth += 1
                    return True
                except:
                    return True
        return False

    def _build_tooltip(self, *largs):
        # Only build the tooltip if it hasn't been created yet
        if self._tooltip:
            return

        cls = self.tooltip_cls
        if isinstance(cls, string_types):
            cls = Factory.get(cls)
        self._tooltip = cls()

        image_widget = self._tooltip.ids.tooltip_image
        image_widget.bind(texture_size=self._update_image_size)
        self._update_image()
        self._update_tooltip()

    def _update_tooltip(self, *largs):
        txt = self.tooltip_txt
        if txt:
            self._tooltip.ids.tooltip_label.text = txt
            self._tooltip.ids.tooltip_label.size = self._tooltip.ids.tooltip_label.texture_size
        else:
            self._tooltip.ids.tooltip_label.text = ''
            self._tooltip.ids.tooltip_label.size = (0, 0)
        
        self._update_tooltip_size()
    
    def _update_image(self, *largs):
        imgpath = self.tooltip_image
        if imgpath:
            self._tooltip.ids.tooltip_image.source = imgpath
            self._tooltip.ids.tooltip_image.visible = True
        else:
            self._tooltip.ids.tooltip_image.source = ''
            self._tooltip.ids.tooltip_image.size = (0, 0)
            self._tooltip.ids.tooltip_image.visible = False

    def _update_image_size(self, instance, value):
        if self.tooltip_image_size:
            self._tooltip.ids.tooltip_image.size = self.tooltip_image_size
        else:
            instance.size = instance.texture_size[0], instance.texture_size[1]

    def _update_tooltip_size(self):
        tooltip_label = self._tooltip.ids.tooltip_label
        tooltip_image = self._tooltip.ids.tooltip_image

        # Calculate new size based on text and image dimensions
        text_width, text_height = tooltip_label.texture_size
        image_width, image_height = tooltip_image.size

        new_width = max(text_width + 20, image_width + 20)
        new_height = text_height + image_height + 20

        # Update tooltip size
        self._tooltip.size = (new_width, new_height)
        self._tooltip.canvas.ask_update()  # Force UI refresh
        self._tooltip.ids.tooltip_label.texture_update()

    def on_mouse_pos(self, *args):
        if not self.show_tooltips:
            self.close_tooltip()
            return
        
        if not self.get_root_window():
            self.close_tooltip()
            return
        
        if not self.tooltip_txt and not self.tooltip_image:
            self.close_tooltip()
            return
        
        if self.disabled:
            self.close_tooltip()
            return
        
        if self._is_blocked_by_modal():
            self.close_tooltip()
            return
        
    
        pos = args[1]
        tooltip_width, tooltip_height = self._tooltip.size
        window_width, window_height = Window.size
        tooltip_label = self._tooltip.ids.tooltip_label
        tooltip_image = self._tooltip.ids.tooltip_image

        text_width = tooltip_label.texture_size[0]
        image_width = tooltip_image.width

        tooltip_padding = 10
        if self.tooltip_image:
            tooltip_padding = 40

        tooltip_width = max(text_width, image_width)
        tooltip_height = tooltip_label.texture_size[1] + tooltip_image.height + tooltip_padding
        self._tooltip.size = (tooltip_width, tooltip_height)
        x = pos[0]
        y = pos[1]
        if x + tooltip_width > window_width:
            x = window_width - tooltip_width - 30

        # Adjust vertical position if too close to the bottom edge
        if y + tooltip_height > window_height - 30:
            y = window_height - tooltip_height - 40
        self._tooltip.pos = (x, y)

        Clock.unschedule(self.display_tooltip) 
        self.close_tooltip() 
        if self.collide_point(*self.to_widget(*pos)):
            Clock.schedule_once(self.display_tooltip, self.tooltip_delay)




    def close_tooltip(self, *args):
        if self._tooltip: #for memory leaks
            Window.remove_widget(self._tooltip)

    def display_tooltip(self, *args):
        Window.add_widget(self._tooltip)


class ToolTipLabel(Label):
    tooltip_txt = StringProperty('')
    tooltip_cls = ObjectProperty(Tooltip)
    tooltip_image = StringProperty('')
    tooltip_delay = NumericProperty(0.5)
    show_tooltips = BooleanProperty(False)
    tooltip_image_size = ObjectProperty(None)

    def __init__(self, **kwargs):
        self._tooltip = None
        super(ToolTipLabel, self).__init__(**kwargs)
        # On iOS, tooltips are not supported, so we disable them
        if sys.platform == 'ios':
            return
        fbind = self.fbind
        fbind('tooltip_cls', self._build_tooltip)
        fbind('tooltip_txt', self._update_tooltip)
        fbind('tooltip_image', self._update_image)
        fbind('tooltip_image_size', self._update_image_size)
        Window.bind(mouse_pos=self.on_mouse_pos)
        self.bind(on_release=self.close_tooltip)
        self._build_tooltip()
        
    def _is_blocked_by_modal(self):
        for child in Window.children:
            if isinstance(child, (Popup, ModalView)):
                try:
                    current = self.parent
                    depth = 0
                    while current and depth < 20:
                        if current == child:
                            return False
                        current = current.parent
                        depth += 1
                    return True
                except:
                    return True
        return False

    def _build_tooltip(self, *largs):
        # Only build the tooltip if it hasn't been created yet
        if self._tooltip:
            return

        cls = self.tooltip_cls
        if isinstance(cls, string_types):
            cls = Factory.get(cls)
        self._tooltip = cls()

        image_widget = self._tooltip.ids.tooltip_image
        image_widget.bind(texture_size=self._update_image_size)
        
        self._update_image()
        self._update_tooltip()

    def _update_tooltip(self, *largs):
        txt = self.tooltip_txt
        if txt:
            self._tooltip.ids.tooltip_label.text = txt
            self._tooltip.ids.tooltip_label.size = self._tooltip.ids.tooltip_label.texture_size
        else:
            self._tooltip.ids.tooltip_label.text = ''
            self._tooltip.ids.tooltip_label.size = (0, 0)
        
        self._update_tooltip_size()
    
    def _update_image(self, *largs):
        imgpath = self.tooltip_image
        if imgpath:
            self._tooltip.ids.tooltip_image.source = imgpath
            self._tooltip.ids.tooltip_image.visible = True
        else:
            self._tooltip.ids.tooltip_image.source = ''
            self._tooltip.ids.tooltip_image.size = (0, 0)
            self._tooltip.ids.tooltip_image.visible = False

    def _update_image_size(self, instance, value):
        if self.tooltip_image_size:
            self._tooltip.ids.tooltip_image.size = self.tooltip_image_size
        else:
            instance.size = instance.texture_size[0], instance.texture_size[1]

    def _update_tooltip_size(self):
        tooltip_label = self._tooltip.ids.tooltip_label
        tooltip_image = self._tooltip.ids.tooltip_image

        # Calculate new size based on text and image dimensions
        text_width, text_height = tooltip_label.texture_size
        image_width, image_height = tooltip_image.size

        new_width = max(text_width + 20, image_width + 20)
        new_height = text_height + image_height + 20

        # Update tooltip size
        self._tooltip.size = (new_width, new_height)
        self._tooltip.canvas.ask_update()  # Force UI refresh
        self._tooltip.ids.tooltip_label.texture_update()

    def on_mouse_pos(self, *args):
        if not self.show_tooltips:
            self.close_tooltip()
            return
        
        if not self.get_root_window():
            self.close_tooltip()
            return
        
        if not self.tooltip_txt and not self.tooltip_image:
            self.close_tooltip()
            return
        
        if self.disabled:
            self.close_tooltip()
            return
        
        if self._is_blocked_by_modal():
            self.close_tooltip()
            return
        
    
        pos = args[1]
        tooltip_width, tooltip_height = self._tooltip.size
        window_width, window_height = Window.size
        tooltip_label = self._tooltip.ids.tooltip_label
        tooltip_image = self._tooltip.ids.tooltip_image

        text_width = tooltip_label.texture_size[0]
        image_width = tooltip_image.width

        tooltip_padding = 10
        if self.tooltip_image:
            tooltip_padding = 40

        tooltip_width = max(text_width, image_width)
        tooltip_height = tooltip_label.texture_size[1] + tooltip_image.height + tooltip_padding
        self._tooltip.size = (tooltip_width, tooltip_height)
        x = pos[0]
        y = pos[1]
        if x + tooltip_width > window_width:
            x = window_width - tooltip_width - 30

        # Adjust vertical position if too close to the bottom edge
        if y + tooltip_height > window_height - 30:
            y = window_height - tooltip_height - 40
        self._tooltip.pos = (x, y)

        Clock.unschedule(self.display_tooltip) 
        self.close_tooltip() 
        if self.collide_point(*self.to_widget(*pos)):
            Clock.schedule_once(self.display_tooltip, self.tooltip_delay)




    def close_tooltip(self, *args):
        if self._tooltip: #for memory leaks
            Window.remove_widget(self._tooltip)

    def display_tooltip(self, *args):
        Window.add_widget(self._tooltip)


