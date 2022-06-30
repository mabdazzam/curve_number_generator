# -*- coding: utf-8 -*-

"""
/***************************************************************************
 CurveNumberGenerator
                                 A QGIS plugin
 This plugin generates a Curve Number layer for the given Area of Interest within the contiguous United States. It can also download Soil, Land Cover, and Impervious Surface datasets for the same area.
 Generated by Plugin Builder: http://g-sherman.github.io/Qgis-Plugin-Builder/
                              -------------------
        begin                : 2020-06-06
        copyright            : (C) 2021 by Abdul Raheem Siddiqui
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
import inspect
import os
import sys

from curve_number_generator.processing.tools.utils import (
    checkPluginUptodate,
    displayUsageMessage,
    incrementUsageCounter,
)
from qgis.core import QgsApplication, QgsProcessingAlgorithm
from qgis.PyQt.QtCore import QCoreApplication
from qgis.PyQt.QtGui import QIcon

cmd_folder = os.path.split(inspect.getfile(inspect.currentframe()))[0]
sys.path.append(cmd_folder)
qgis_settings_path = QgsApplication.qgisSettingsDirPath().replace("\\", "/")
cn_log_path = os.path.join(qgis_settings_path, "curve_number_generator.log")

__author__ = "Abdul Raheem Siddiqui"
__date__ = "2022-06-29"
__copyright__ = "(C) 2021 by Abdul Raheem Siddiqui"

# This will get replaced with a git SHA1 when you do a git archive

__revision__ = "$Format:%H$"

curr_version = "1.3"


class CurveNumberGeneratorAlgorithm(QgsProcessingAlgorithm):

    # Constants used to refer to parameters and outputs. They will be
    # used when calling the algorithm from another algorithm, or when
    # calling from the QGIS console.

    OUTPUT = "OUTPUT"
    INPUT = "INPUT"

    def postProcessAlgorithm(self, context, feedback):
        try:  # try-except because trivial features
            counter = incrementUsageCounter()

            # check if counter is milestone for plugin version check
            if (counter) % 4 == 0:
                checkPluginUptodate("Curve Number Generator")

            # check if counter is milestone for usage message
            if (counter) % 25 == 0:
                displayUsageMessage(counter)

        except Exception as e:
            feedback.reportError(
                f"Algorithm finished successfully but post processing failed. {e}",
                False,
            )

        return {}

    def group(self):
        """
        Returns the name of the group this algorithm belongs to. This string
        should be localised.
        """
        return self.tr(self.groupId())

    def groupId(self):
        """
        Returns the unique ID of the group this algorithm belongs to. This
        string should be fixed for the algorithm, and must not be localised.
        The group id should be unique within each provider. Group id should
        contain lowercase alphanumeric characters only and no spaces or other
        formatting characters.
        """
        return ""

    def icon(self):
        cmd_folder = os.path.split(inspect.getfile(inspect.currentframe()))[0]
        icon = QIcon(
            os.path.join(os.path.join(os.path.dirname(cmd_folder), "icon.png"))
        )
        return icon

    def tr(self, string):
        return QCoreApplication.translate("Processing", string)

    def helpUrl(self):
        return "mailto:ars.work.ce@gmail.com"
