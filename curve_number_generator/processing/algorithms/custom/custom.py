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

import processing

from curve_number_generator.processing.curve_number_generator_algorithm import (
    CurveNumberGeneratorAlgorithm,
)
from curve_number_generator.processing.tools.curve_numper import CurveNumber
from curve_number_generator.processing.tools.utils import (
    clip,
    fixGeometries,
    gdalPolygonize,
)
from qgis.core import (
    QgsProcessing,
    QgsProcessingMultiStepFeedback,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterField,
    QgsProcessingParameterRasterLayer,
    QgsProcessingParameterVectorDestination,
    QgsProcessingParameterVectorLayer,
)

cmd_folder = os.path.split(inspect.getfile(inspect.currentframe()))[0]
sys.path.append(cmd_folder)

__author__ = "Abdul Raheem Siddiqui"
__date__ = "2021-08-04"
__copyright__ = "(C) 2021 by Abdul Raheem Siddiqui"

# This will get replaced with a git SHA1 when you do a git archive

__revision__ = "$Format:%H$"


class Custom(CurveNumberGeneratorAlgorithm):

    # Constants used to refer to parameters and outputs. They will be
    # used when calling the algorithm from another algorithm, or when
    # calling from the QGIS console.

    OUTPUT = "OUTPUT"
    INPUT = "INPUT"

    def initAlgorithm(self, config=None):

        self.addParameter(
            QgsProcessingParameterFeatureSource(
                "aoi",
                "Area of Interest",
                types=[QgsProcessing.TypeVectorPolygon],
                defaultValue=None,
            )
        )
        self.addParameter(
            QgsProcessingParameterRasterLayer(
                "LandCover", "Land Cover Raster", defaultValue=None
            )
        )
        self.addParameter(
            QgsProcessingParameterVectorLayer(
                "Soils",
                "Soils Layer",
                types=[QgsProcessing.TypeVectorPolygon],
                defaultValue=None,
            )
        )
        self.addParameter(
            QgsProcessingParameterField(
                "SoilLookupField",
                "Soil Lookup Field",
                parentLayerParameterName="Soils",
                allowMultiple=False,
                defaultValue=None,
            )
        )
        self.addParameter(
            QgsProcessingParameterVectorLayer(
                "CnLookup",
                "Lookup Table",
                types=[QgsProcessing.TypeVector],
                defaultValue="",
            )
        )
        self.addParameter(
            QgsProcessingParameterVectorDestination(
                "CurveNumber",
                "Curve Number",
                defaultValue=None,
            )
        )

    def processAlgorithm(self, parameters, context, model_feedback):
        # Use a multi-step feedback, so that individual child algorithm progress reports are adjusted for the
        # overall progress through the model
        feedback = QgsProcessingMultiStepFeedback(8, model_feedback)
        results = {}
        outputs = {}

        # Prepare Land Cover for Curve Number Calculation
        # Polygonize (raster to vector)
        outputs["LandCoverPolygonize"] = gdalPolygonize(
            parameters["LandCover"],
            "land_cover",
            context=context,
            feedback=feedback,
        )

        step = 1
        feedback.setCurrentStep(step)
        if feedback.isCanceled():
            return {}

        # Fix geometries
        outputs["LandCoverVector"] = fixGeometries(
            outputs["LandCoverPolygonize"],
            context=context,
            feedback=feedback,
        )

        step += 1
        feedback.setCurrentStep(step)
        if feedback.isCanceled():
            return {}

        # Clip to AOI
        outputs["LandCoverClipped"] = clip(
            outputs["LandCoverVector"],
            parameters["aoi"],
            context=context,
            feedback=feedback,
        )

        step += 1
        feedback.setCurrentStep(step)
        if feedback.isCanceled():
            return {}

        curve_number = CurveNumber(
            outputs["LandCoverClipped"],
            parameters["Soils"],
            parameters["CnLookup"],
            context=context,
            feedback=feedback,
        )

        try:
            parameters["CurveNumber"].destinationName = "Curve Number"
        except AttributeError:
            pass

        results["CurveNumber"], step = curve_number.generateCurveNumber(
            [f"{parameters['SoilLookupField']}"],
            [],
            f'''"land_cover" || "{parameters['SoilLookupField']}"''',
            start_step=step + 1,
            output=parameters["CurveNumber"],
        )

        step += 1
        feedback.setCurrentStep(step)
        if feedback.isCanceled():
            return {}

        cn_style_path = os.path.join(os.path.dirname(cmd_folder), "curve_number.qml")
        self.handle_post_processing(results["CurveNumber"], cn_style_path, context)

        return results

    def name(self):
        """
        Returns the algorithm name, used for identifying the algorithm. This
        string should be fixed for the algorithm, and must not be localised.
        The name should be unique within each provider. Names should contain
        lowercase alphanumeric characters only and no spaces or other
        formatting characters.
        """
        return "custom"

    def displayName(self):
        """
        Returns the translated algorithm name, which should be used for any
        user-visible display of the algorithm name.
        """
        return self.tr("Curve Number Generator (Custom)")

    def shortHelpString(self):
        return """"""

    def createInstance(self):
        return Custom()
