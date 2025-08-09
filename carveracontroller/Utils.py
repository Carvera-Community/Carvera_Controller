# -*- coding: ascii -*-
# $Id$
#
# Author:	Vasilis.Vlachoudis@cern.ch
# Date:	16-Apr-2015

from __future__ import absolute_import
from __future__ import print_function
__author__ = "Vasilis Vlachoudis"
__email__  = "vvlachoudis@gmail.com"

import os
import sys
import hashlib
import glob
import traceback
try:
	import ConfigParser
except ImportError:
	import configparser as ConfigParser

import gettext
try:
	import __builtin__
except:
	import builtins as __builtin__
	#__builtin__.unicode = str		# dirty hack for python3

try:
	import serial
except:
	serial = None

from datetime import datetime
from kivy.clock import Clock

__prg__     = "bCNC"
__tool__    = "TOOL"
prgpath   = os.path.abspath(os.path.dirname(sys.argv[0]))
iniSystem = os.path.join(prgpath,"%s.ini"%(__prg__))
iniUser   = os.path.expanduser("~/.%s" % (__prg__))
hisFile   = os.path.expanduser("~/.%s.history" % (__prg__))
iniTool   = os.path.expanduser("~/.%s" % (__tool__))

# dirty way of substituting the "_" on the builtin namespace
#__builtin__.__dict__["_"] = gettext.translation('bCNC', 'locale', fallback=True).ugettext
__builtin__._ = gettext.translation('bCNC', os.path.join(prgpath,'locale'), fallback=True).gettext
__builtin__.N_ = lambda message: message


icons     = {}
images     = {}
config    = ConfigParser.ConfigParser()
toolconfig = ConfigParser.ConfigParser()
language  = ""

_errorReport = True
errors       = []
_maxRecent   = 10

_FONT_SECTION = "Font"


#New class to provide config for everyone
#FIXME: create single instance of this and pass it to all parts of application
class Config():
	def greet(self, who=__name__):
		print("Config class loaded in %s"%(who))


#------------------------------------------------------------------------------
# Load configuration
#------------------------------------------------------------------------------
def loadConfiguration(systemOnly=False):
	global config, _errorReport, language
	if systemOnly:
		config.read(iniSystem)
	else:
		config.read([iniSystem, iniUser])
		_errorReport = getInt("Connection","errorreport",1)

		language = getStr(__prg__, "language")
		if language:
			# replace language
			__builtin__._ = gettext.translation('bCNC', os.path.join(prgpath,'locale'),
					fallback=True, languages=[language]).gettext


#------------------------------------------------------------------------------
# Save configuration file
#------------------------------------------------------------------------------
def saveConfiguration():
	global config
	cleanConfiguration()
	f = open(iniUser,"w")
	config.write(f)
	f.close()

#----------------------------------------------------------------------
# Remove items that are the same as in the default ini
#----------------------------------------------------------------------
def cleanConfiguration():
	global config
	newconfig = config	# Remember config
	config = ConfigParser.ConfigParser()

	loadConfiguration(True)

	# Compare items
	for section in config.sections():
		for item, value in config.items(section):
			try:
				new = newconfig.get(section, item)
				if value==new:
					newconfig.remove_option(section, item)
			except ConfigParser.NoOptionError:
				pass
	config = newconfig

#------------------------------------------------------------------------------
# Load tool config
#------------------------------------------------------------------------------
def loadToolConfig():
	global toolconfig
	toolconfig.read(iniTool)

#------------------------------------------------------------------------------
# Save tool config
#------------------------------------------------------------------------------
def saveToolConfig():
	global toolconfig
	f = open(iniTool, "w")
	toolconfig.write(f)
	f.close()

#------------------------------------------------------------------------------
# add section if it doesn't exist
#------------------------------------------------------------------------------
def addSection(section):
	global config
	if not config.has_section(section):
		config.add_section(section)


#------------------------------------------------------------------------------
def getStr(section, name, default=""):
	global config
	try:
		return config.get(section, name)
	except:
		return default


#------------------------------------------------------------------------------
def getUtf(section, name, default=""):
	global config
	try:
		return config.get(section, name).decode("utf8")
	except:
		return default


#------------------------------------------------------------------------------
def getInt(section, name, default=0):
	global config
	try: return int(config.get(section, name))
	except: return default


#------------------------------------------------------------------------------
def getFloat(section, name, default=0.0):
	global config
	try: return float(config.get(section, name))
	except: return default


#------------------------------------------------------------------------------
def getBool(section, name, default=False):
	global config
	try: return bool(int(config.get(section, name)))
	except: return default


#------------------------------------------------------------------------------
def getToolInt(section, name, default=0):
	global toolconfig
	try: return int(toolconfig.get(section, name))
	except: return default


#------------------------------------------------------------------------------
def getToolFloat(section, name, default=0.0):
	global toolconfig
	try: return float(toolconfig.get(section, name))
	except: return default

#------------------------------------------------------------------------------
def setToolStr(section, name, value):
	global toolconfig
	if not toolconfig.has_section(section):
		toolconfig.add_section(section)
	toolconfig.set(section, name, str(value))




#-------------------------------------------------------------------------------
# Set font in configuration
#-------------------------------------------------------------------------------
def setFont(name, font):
	if font is None: return
	if isinstance(font,str):
		config.set(_FONT_SECTION, name, font)
	elif isinstance(font,tuple):
		config.set(_FONT_SECTION, name, ",".join(map(str,font)))
	else:
		config.set(_FONT_SECTION, name, "%s,%s,%s" % \
			(font.cget("family"),font.cget("size"),font.cget("weight")))


#------------------------------------------------------------------------------
def setBool(section, name, value):
	global config
	config.set(section, name, str(int(value)))


#------------------------------------------------------------------------------
def setStr(section, name, value):
	global config
	config.set(section, name, str(value))


#------------------------------------------------------------------------------
def setUtf(section, name, value):
	global config
	try:
		s = str(value.encode("utf8"))
	except:
		s = str(value)
	config.set(section, name, s)

setInt   = setStr
setFloat = setStr


#-------------------------------------------------------------------------------
# Add Recent
#-------------------------------------------------------------------------------
def addRecent(filename):
	try:
		sfn = str(os.path.abspath(filename))
	except UnicodeEncodeError:
		sfn = filename.encode("utf8")

	last = _maxRecent-1
	for i in range(_maxRecent):
		rfn = getRecent(i)
		if rfn is None:
			last = i-1
			break
		if rfn == sfn:
			if i==0: return
			last = i-1
			break

	# Shift everything by one
	for i in range(last, -1, -1):
		config.set("File", "recent.%d"%(i+1), getRecent(i))
	config.set("File", "recent.0", sfn)


#-------------------------------------------------------------------------------
def getRecent(recent):
	try:
		return config.get("File","recent.%d"%(recent))
	except ConfigParser.NoOptionError:
		return None


#------------------------------------------------------------------------------
# Return all comports when serial.tools.list_ports is not available!
#------------------------------------------------------------------------------
def comports(include_links=True):
	locations=[	'/dev/ttyACM',
			'/dev/ttyUSB',
			'/dev/ttyS',
			'com']

	comports = []
	for prefix in locations:
		for i in range(32):
			device = "%s%d"%(prefix,i)
			try:
				os.stat(device)
				comports.append((device,None,None))
			except OSError:
				pass

			# Detects windows XP serial ports
			try:
				s = serial.Serial(device)
				s.close()
				comports.append((device,None,None))
			except:
				pass
	return comports

suffixes = ['B', 'KB', 'MB', 'GB', 'TB', 'PB']

#------------------------------------------------------------------------------
# Return readable size string
#------------------------------------------------------------------------------
def humansize(nbytes):
    nbytes = int(nbytes)
    i = 0
    while nbytes >= 1024 and i < len(suffixes)-1:
        nbytes /= 1024.
        i += 1
    f = ('%.2f' % nbytes).rstrip('0').rstrip('.')
    return '%s %s' % (f, suffixes[i])

#------------------------------------------------------------------------------
# Return readable date string
#------------------------------------------------------------------------------
def humandate(date):
    return datetime.fromtimestamp(date).strftime("%Y-%m-%d %H:%M")

#------------------------------------------------------------------------------
# Return hours, minutes, seconds from seconds
#------------------------------------------------------------------------------
def second2hour(seconds):
    total_seconds = int(seconds)
    hour = total_seconds // 3600
    total_seconds = total_seconds % 3600
    minute = total_seconds // 60
    total_seconds = total_seconds % 60
    second = total_seconds
    ret_value = str(second) + 's'
    if minute > 0:
        ret_value = str(minute) + 'm' + ret_value
    if hour > 0:
        ret_value = str(hour) + 'h' + ret_value
    return ret_value

#------------------------------------------------------------------------------
# Return md5 of a file
#------------------------------------------------------------------------------
def md5(filename):
    hash_md5 = hashlib.md5()
    with open(filename, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()

#------------------------------------------------------------------------------
# Return float array
#------------------------------------------------------------------------------
def xfrange(start, stop, steps):
    if steps <= 1:
        return
    interval = (stop - start) / (steps - 1)
    i = 0
    if interval == 0:
        for i in range(steps):
            yield start
    else:
        while start + i * interval <= stop:
            yield start + i * interval
            i += 1

#------------------------------------------------------------------------------
# Return float array
#------------------------------------------------------------------------------
def translate(value, leftMin, leftMax, rightMin, rightMax):
    # Figure out how 'wide' each range is
    leftSpan = leftMax - leftMin
    rightSpan = rightMax - rightMin

    # Convert the left range into a 0-1 range (float)
    valueScaled = float(value - leftMin) / float(leftSpan)

    # Convert the 0-1 range into a value in the right range.
    return rightMin + (valueScaled * rightSpan)

#------------------------------------------------------------------------------
# convert from config string
#------------------------------------------------------------------------------
def from_config(type, value_string):
    if type == 'bool':
        if value_string.lower() == "true":
            return 1
        else:
            return 0
    elif type == 'numeric':
        return float(value_string)
    else:
        return value_string

#------------------------------------------------------------------------------
# convert from config string to panel value
#------------------------------------------------------------------------------
def from_config(type, value_string):
    if type == 'bool':
        if value_string.lower() == "true":
            return 1
        else:
            return 0
    elif type == 'numeric':
        return float(value_string)
    else:
        return value_string

#------------------------------------------------------------------------------
# convert from config string
#------------------------------------------------------------------------------
def to_config(type, value_string):
    if type == 'bool':
        if value_string.lower() == "1":
            return 'true'
        else:
            return 'false'
    else:
        return value_string

def digitize_v(version):
    # Clean version string by removing non-numeric suffixes like 'c', 'rc', etc.
    v_list = version.split('.')
    cleaned_parts = []
    for part in v_list:
        # Extract only the numeric portion at the beginning
        numeric_part = ""
        for char in part:
            if char.isdigit():
                numeric_part += char
            else:
                break
        cleaned_parts.append(int(numeric_part if numeric_part else "0"))
    
    # Ensure we have at least 3 parts (major.minor.patch)
    while len(cleaned_parts) < 3:
        cleaned_parts.append(0)

    # default controller version (until build script runs) is 0.0.0
    # This should be treated as the "latest" version
    if cleaned_parts[0] == 0:
        cleaned_parts[0] = 999

    return cleaned_parts[0] * 1000 * 1000 + cleaned_parts[1] * 1000 + cleaned_parts[2]

#------------------------------------------------------------------------------
# Auto selection for text inputs
#------------------------------------------------------------------------------
def bind_auto_select_to_text_input(widget):
	def focus_handler(input, value):
		if value:
			Clock.schedule_once(lambda _: widget.select_all(), 0.1)
	widget.bind(focus=focus_handler)
