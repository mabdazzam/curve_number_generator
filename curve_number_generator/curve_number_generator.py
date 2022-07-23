# -*- coding: utf-8 -*-

"""
/***************************************************************************
 CurveNumberGenerator
                                 A QGIS plugin
 This plugin generates a Curve Number layer for the given Area of Interest within the contiguous United States. It can also download Soil, Land Cover, and Impervious Surface datasets for the same area.
 Generated by Plugin Builder: http://g-sherman.github.io/Qgis-Plugin-Builder/
                              -------------------
        begin                : 2022-07-22
        copyright            : (C) 2022 by Abdul Raheem Siddiqui
        email                : mailto:ars.work.ce@gmail.com
 ***************************************************************************/

/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 ***************************************************************************/
"""

__author__ = "Abdul Raheem Siddiqui"
__date__ = "2021-08-04"
__copyright__ = "(C) 2021 by Abdul Raheem Siddiqui"

# This will get replaced with a git SHA1 when you do a git archive

__revision__ = "$Format:%H$"

import inspect
import os
import sys

from qgis.core import QgsApplication, QgsProcessingAlgorithm
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction

import processing
from curve_number_generator.processing.curve_number_generator_provider import \
    CurveNumberGeneratorProvider

cmd_folder = os.path.split(inspect.getfile(inspect.currentframe()))[0]
if cmd_folder not in sys.path:
    sys.path.insert(0, cmd_folder)


class CurveNumberGeneratorPlugin(object):
    def __init__(self, iface):
        self.provider = None
        self.iface = iface

    def initProcessing(self):
        """Init Processing provider for QGIS >= 3.8."""
        self.provider = CurveNumberGeneratorProvider()
        QgsApplication.processingRegistry().addProvider(self.provider)

    def initGui(self):
        self.initProcessing()

        icon = os.path.join(os.path.join(cmd_folder, "icon.png"))
        self.action = QAction(
            QIcon(icon), "Curve Number Generator", self.iface.mainWindow()
        )
        self.action.triggered.connect(self.run)
        self.iface.addPluginToMenu("&CurveNumberGenerator", self.action)

    def unload(self):
        QgsApplication.processingRegistry().removeProvider(self.provider)
        self.iface.removePluginMenu("&CurveNumberGenerator", self.action)

    def run(self):
        processing.execAlgorithmDialog("Curve Number Generator:Curve Number Generator")
