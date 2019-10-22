#!/usr/bin/python

import json
import urllib
import urllib2
from cookielib import CookieJar
from HTMLParser import HTMLParser
import pygame
from time import sleep
from time import time
import StringIO
from math import ceil
import csv
import httplib
import datetime
import socket
import threading

# Start in fullscreen. Use "f" to toggle.
fullscreen = True
# Display all cameras using the following aspect ratio.
# Used for constructing the grid of images.
sourceWidth = 640
sourceHeight = 480

#Extracts URL for camera image feed from ZoneMinder camera view UI.
class MyHTMLParser(HTMLParser):
    def handle_starttag(self, tag, attrs):
        if tag == "img":
            for attr in attrs:
                if attr[0] == "id" and attr[1] == "liveStream":
                    for attr in attrs:
                        if attr[0] == "src":
                            self.data = attr[1]

class ZMSource:
    def __init__(self,username, password, zmserver, protocol, monitorid,
                 renderX,renderY,renderWidth,renderHeight):
        self.__username = username
        self.__password = password
        self.__zmserver = zmserver
        self.__monitorid = monitorid
        self.__protocol = protocol
        self.__renderX = int(renderX)
        self.__renderY = int(renderY)
        self.__renderWidth = int(renderWidth)
        self.__renderHeight = int(renderHeight)
        self.__healthyRefreshDelay = config["global"]["cameraRefreshDelay"]
        # delay between refresh attempts when source has exceeded
        # the broken refresh count limit. This prevents hammering
        # ZM servers that have issues.
        self.__brokenRefreshDelay = 60 
        self.__brokenRefreshCount = 0
        self.__brokenRefreshCountLimit = int(config["global"]["secondsBeforeBroken"] / self.__healthyRefreshDelay)
        self.__refreshDelay = self.__healthyRefreshDelay
        self.__pygameImage = "" #stores the current camera image
        self.__lastUpdateTime = 0 #when did we last update self.__pygameImage
        self.__singleJPEGURL = self.__protocol + "://{0}/cgi-bin/zms?mode=single&monitor={1}&user={2}&pass={3}".format(zmserver,monitorid,username,password)
    def __incrementBrokenRefreshCount(self):
        self.__brokenRefreshCount += 1
        if(self.__brokenRefreshCount >= self.__brokenRefreshCountLimit):
            self.__refreshDelay = self.__brokenRefreshDelay
    def __resetBrokenRefreshCount(self):
        self.__brokenRefreshCount = 0
        self.__refreshDelay = self.__healthyRefreshDelay
    def update(self):
        if(self.__pygameImage != "" and 
           (time() - self.__lastUpdateTime) < self.__refreshDelay):
            return
        self.__lastUpdateTime = time()
        try:
            response = urllib2.urlopen(urllib2.Request(self.__singleJPEGURL))
        except httplib.BadStatusLine:
            #Happens about every two hours with ZM 1.25.
            print "Error (httplib.BadStatusLine) fetching updated camera image from %s:%s at %s" % (
                self.__zmserver,self.__monitorid,str(datetime.datetime.now()))
            self.__incrementBrokenRefreshCount()
            return
        except urllib2.URLError, e:
            #Happens when the server takes too long to respond.
            print "Error (urllib2.URLError) fetching updated camera image from %s:%s at %s" % (
                self.__zmserver,self.__monitorid,str(datetime.datetime.now()))
            print str(e)
            print "If the error reports that certificate verification failed, it may be necessary to install organization-local certificate authorities."
            self.__incrementBrokenRefreshCount()
            return
        imageString = response.read()
        imageFD = StringIO.StringIO(imageString)
        try:
            self.__pygameImage = pygame.image.load(imageFD)
        except pygame.error:
            #Happens when the ZM server is in the process of restarting.
            self.__incrementBrokenRefreshCount()
            return
        self.__resetBrokenRefreshCount()
    def render(self):
        if(self.__brokenRefreshCount >= self.__brokenRefreshCountLimit):
            # Camera has not yielded an image in a while.
            pygame.draw.rect(screen, (0,0,255),
                             (self.__renderX, self.__renderY,
                              self.__renderWidth, self.__renderHeight))
            return
        try:
            transformedPygameImage = pygame.transform.smoothscale(self.__pygameImage,
                                                    (self.__renderWidth,
                                                     self.__renderHeight))
        except TypeError:
            #Happens when the script has never been able to fetch an image
            #from the remote server. Usually a consequence of the remote server
            #being offline when the script starts
            return
        screen.blit(transformedPygameImage,(self.__renderX,self.__renderY))

def createSlots(screenWidth, screenHeight,
                sourceWidth, sourceHeight,
                numSources, overscan):
    layoutOptions = []
    for columns in range(1,numSources+1):
        rows = int(ceil(float(numSources)/columns))
        maxWidthByCols = float(screenWidth - 2*overscan)/columns
        maxWidthByRows = float(screenHeight - 2*overscan)/rows * sourceWidth / sourceHeight
        layoutOption = {}
        layoutOption["columns"] = columns
        layoutOption["rows"] = rows
        layoutOption["fitness"] = min(maxWidthByCols,maxWidthByRows)
        layoutOptions.append(layoutOption)
    sortedLayoutOptions = sorted(layoutOptions,
                                 key=(lambda x: x["fitness"]))
    bestLayout = sortedLayoutOptions.pop()
    rows = bestLayout["rows"]
    columns = bestLayout["columns"]
    imageWidth = int(ceil(float(screenWidth - 2*overscan) / columns))
    imageHeight = int(ceil(float(screenHeight - 2*overscan) / rows))
    slots = []
    for row in reversed(range(rows)):
        for column in reversed(range(columns)):
            xposition = overscan + column * imageWidth
            yposition = overscan + row * imageHeight
            width = int(min(imageWidth,
                            float(imageHeight)/sourceHeight * sourceWidth))
            height = int(min(imageHeight,
                             float(imageWidth)/sourceWidth * sourceHeight))
            slot = {"xposition":xposition,
                    "yposition":yposition,
                    "width":width,
                    "height":height}
            slots.append(slot)
    return slots

def init():
    global config
    global screen
    global cameras

    pygame.display.quit()
    if(fullscreen == True):
        screen = pygame.display.set_mode((0,0),pygame.FULLSCREEN)
    else:
        screen = pygame.display.set_mode((640,480))

    with open("config.json") as configfile:
        config = json.loads(configfile.read())
    config["global"]["overscan"] = int(config["global"]["overscan"])
    config["global"]["cameraRefreshDelay"] = float(config["global"]["cameraRefreshDelay"])
    config["global"]["secondsBeforeBroken"] = int(config["global"]["secondsBeforeBroken"])
    config["global"]["cycleDelay"] = int(config["global"]["cycleDelay"])
    
    infoObject = pygame.display.Info()
    screenWidth = infoObject.current_w
    screenHeight = infoObject.current_h

    if config["global"]["mode"] == "montage":
        slots = createSlots(screenWidth,screenHeight,
                            sourceWidth,sourceHeight,
                            len(config["cameras"]),config["global"]["overscan"])

        cameras = []
        for source in config["cameras"]:
            slot = slots.pop()
            cameras.append(ZMSource(source["username"],source["password"],
                                    source["zmserver"],source["protocol"],
                                    source["monitorid"],
                                    slot["xposition"],slot["yposition"],
                                    slot["width"],slot["height"]))
    elif config["global"]["mode"] == "cycle":
        cameras = []
        for source in config["cameras"]:
            cameras.append(ZMSource(source["username"],source["password"],
                                    source["zmserver"],source["monitorid"],
                                    0,0,screenWidth,screenHeight))
    else:
        print "unsupported 'mode' in config file"
        exit(1)
        
    pygame.mouse.set_visible(False)

def update():
    # Running update threads in parallel helps reduce impact
    # of network delay on framerate. With 4 cameras updating
    # serially, an update takes 0.4-0.5s to complete. With
    # 4 cameras updating in parallel, it takes around 0.15s.

    ## Fetching only those cameras we think are about to be rendered
    ## may be premature optimization.
    # if config["global"]["mode"] == "montage":
        # threads = []
        # for camera in cameras:
        #     camera.update()
        #     t = threading.Thread(target=camera.update)
        #     t.start()
        #     threads.append(t)
        # for t in threads:
        #     t.join()
    for camera in cameras:
        camera.update()
    # elif config["global"]["mode"] == "cycle":
    #     print "cycle mode not yet supported"
    #     exit(1)
    # else:
    #     print "unsupported 'mode' in config file"
    #     exit(1)

def render():
    screen.fill((0,0,0))
    if config["global"]["mode"] == "montage":
        for camera in cameras:
            camera.render()
    elif config["global"]["mode"] == "cycle":
        selectedCamera = int(time()) % (config["global"]["cycleDelay"] * len(cameras)) / config["global"]["cycleDelay"]
        cameras[selectedCamera].render()
    else:
        print "unsupported 'mode' in config file"
        exit(1)
    pygame.display.flip()

screen = []
cameras = []

init()
while True:
    for event in pygame.event.get():
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_q or event.key == pygame.K_ESCAPE:
                quit()
            if event.key == pygame.K_f:
                if fullscreen == True:
                    fullscreen = False
                    init()
                else:
                    fullscreen = True
                    init()
    update()
    render()
    sleep(.1)
