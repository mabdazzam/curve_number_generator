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
import sys
import inspect
import codecs
import os
from curve_number_generator.processing.algorithms.conus_nlcd_ssurgo.ssurgo_soil import (
    SsurgoSoil,
)
import processing
from qgis.PyQt.QtGui import QIcon
from qgis.core import (
    QgsApplication,
    QgsProcessing,
    QgsProcessingParameterFeatureSource,
    QgsProcessingMultiStepFeedback,
    QgsProcessingParameterVectorLayer,
    QgsProcessingParameterBoolean,
    QgsProcessingParameterDefinition,
    QgsCoordinateReferenceSystem,
    QgsExpression,
    QgsVectorLayer,
    QgsField,
    QgsFeature,
    QgsUnitTypes,
    QgsProcessingException,
    QgsProcessingOutputHtml,
    QgsProcessingParameterRasterDestination,
    QgsProcessingParameterVectorDestination,
)

from tempfile import NamedTemporaryFile

from curve_number_generator.processing.tools.utils import (
    checkAreaLimits,
    createRequestBBOXDim,
    downloadFile,
    fixGeometries,
    gdalWarp,
    getExtent,
    getExtentArea,
    reprojectLayer,
    gdalPolygonize,
)

from curve_number_generator.processing.tools.curve_numper import CurveNumber

from curve_number_generator.processing.config import CONUS_NLCD_SSURGO
from curve_number_generator.processing.curve_number_generator_algorithm import (
    CurveNumberGeneratorAlgorithm,
)


cmd_folder = os.path.split(inspect.getfile(inspect.currentframe()))[0]
sys.path.append(cmd_folder)
qgis_settings_path = QgsApplication.qgisSettingsDirPath().replace("\\", "/")
cn_log_path = os.path.join(qgis_settings_path, "curve_number_generator.log")

__author__ = "Abdul Raheem Siddiqui"
__date__ = "2021-08-04"
__copyright__ = "(C) 2021 by Abdul Raheem Siddiqui"

# This will get replaced with a git SHA1 when you do a git archive

__revision__ = "$Format:%H$"

curr_version = "1.3"

debug = True


class ConusNlcdSsurgo(CurveNumberGeneratorAlgorithm):

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
            QgsProcessingParameterVectorLayer(
                "aoi",
                "Area of Interest",
                types=[QgsProcessing.TypeVectorPolygon],
                defaultValue=None,
            )
        )
        param = QgsProcessingParameterVectorLayer(
            "CnLookup",
            "Lookup Table",
            optional=True,
            types=[QgsProcessing.TypeVector],
            defaultValue="",
        )
        param.setFlags(param.flags() | QgsProcessingParameterDefinition.FlagAdvanced)
        self.addParameter(param)
        param = QgsProcessingParameterBoolean(
            "drainedsoilsleaveuncheckedifnotsure",
            "Drained Soils? [leave unchecked if not sure]",
            defaultValue=False,
        )
        param.setFlags(param.flags() | QgsProcessingParameterDefinition.FlagAdvanced)
        self.addParameter(param)
        self.addParameter(
            QgsProcessingParameterRasterDestination(
                "NLCDLandCover",
                "NLCD Land Cover",
                optional=True,
                createByDefault=False,
                defaultValue=None,
            )
        )
        self.addParameter(
            QgsProcessingParameterRasterDestination(
                "NLCDImpervious",
                "NLCD Impervious Surface",
                optional=True,
                createByDefault=False,
                defaultValue=None,
            )
        )
        self.addParameter(
            QgsProcessingParameterVectorDestination(
                "Soils",
                "Soils",
                optional=True,
                createByDefault=False,
                defaultValue=None,
            )
        )
        self.addParameter(
            QgsProcessingParameterVectorDestination(
                "CurveNumber",
                "Curve Number",
                optional=True,
                createByDefault=False,
                defaultValue=None,
            )
        )

    def processAlgorithm(self, parameters, context, model_feedback):
        # Use a multi-step feedback, so that individual child algorithm progress reports are adjusted for the
        # overall progress through the model
        feedback = QgsProcessingMultiStepFeedback(25, model_feedback)
        results = {}
        outputs = {}

        # Assiging Default CN_Lookup Table
        if parameters["CnLookup"] == None:
            csv_uri = (
                "file:///"
                + os.path.join(cmd_folder, "default_lookup.csv")
                + "?delimiter=,"
            )
            csv = QgsVectorLayer(csv_uri, "default_lookup.csv", "delimitedtext")
            parameters["CnLookup"] = csv

        area_layer = self.parameterAsVectorLayer(parameters, "aoi", context)
        orig_epsg_code = (
            area_layer.crs().authid()
        )  # preserve orignal epsg_code to project back to it

        # Reproject layer to EPSG:5070
        outputs["ReprojectLayer5070"] = reprojectLayer(
            parameters["aoi"],
            QgsCoordinateReferenceSystem("EPSG:5070"),
            context=context,
            feedback=feedback,
        )
        area_layer = context.takeResultLayer(outputs["ReprojectLayer5070"])

        epsg_code = area_layer.crs().authid()

        step = 1
        feedback.setCurrentStep(step)
        if feedback.isCanceled():
            return {}

        area_acres = getExtentArea(area_layer, QgsUnitTypes.AreaAcres)

        checkAreaLimits(area_acres, 100000, 500000, feedback=feedback)
        extent = getExtent(area_layer)
        bbox_dim = createRequestBBOXDim(extent, 30)

        # NLCD Impervious Raster
        if parameters.get("NLCDImpervious", None):
            outputs["DownloadNlcdImp"] = downloadFile(
                CONUS_NLCD_SSURGO["NLCD_IMP_2019"].format(
                    epsg_code,
                    bbox_dim[0],
                    bbox_dim[1],
                    ",".join([str(item) for item in extent]),
                ),
                "https://www.mrlc.gov/geoserver/mrlc_display/NLCD_2019_Impervious_L48/ows",
                "Error requesting land use data from 'www.mrlc.gov'. Most probably because either their server is down or there is a certification issue.\nThis should be temporary. Try again later.\n",
                context=context,
                feedback=feedback,
            )

            step += 1
            feedback.setCurrentStep(step)
            if feedback.isCanceled():
                return {}

            # failing if called by processing.run()
            try:
                parameters["NLCDImpervious"].destinationName = "NLCD Impervious Surface"
            except AttributeError:
                pass

            # reproject to original crs
            # Warp (reproject)
            results["NLCDImpervious"] = gdalWarp(
                outputs["DownloadNlcdImp"],
                QgsCoordinateReferenceSystem(str(orig_epsg_code)),
                parameters["NLCDImpervious"],
                context=context,
                feedback=feedback,
            )

            step += 1
            feedback.setCurrentStep(step)
            if feedback.isCanceled():
                return {}

        # NLCD Land Cover Data
        if any(
            [parameters.get("NLCDLandCover", None), parameters.get("CurveNumber", None)]
        ):
            outputs["DownloadNlcdLC"] = downloadFile(
                CONUS_NLCD_SSURGO["NLCD_LC_2019"].format(
                    epsg_code,
                    bbox_dim[0],
                    bbox_dim[1],
                    ",".join([str(item) for item in extent]),
                ),
                "https://www.mrlc.gov/geoserver/mrlc_display/NLCD_2019_Land_Cover_L48/ows",
                "Error requesting land use data from 'www.mrlc.gov'. Most probably because either their server is down or there is a certification issue.\nThis should be temporary. Try again later.\n",
                context=context,
                feedback=feedback,
            )

            step += 1
            feedback.setCurrentStep(step)
            if feedback.isCanceled():
                return {}

            if parameters.get("NLCDLandCover", None):
                try:
                    parameters["NLCDLandCover"].destinationName = "NLCD Land Cover"
                except AttributeError:
                    pass

                lc_output = parameters["NLCDLandCover"]
            else:
                lc_output = QgsProcessing.TEMPORARY_OUTPUT

            # reproject to original crs
            # Warp (reproject)
            results["NLCDLandCover"] = gdalWarp(
                outputs["DownloadNlcdLC"],
                QgsCoordinateReferenceSystem(str(orig_epsg_code)),
                lc_output,
                context=context,
                feedback=feedback,
            )

            step += 1
            feedback.setCurrentStep(step)
            if feedback.isCanceled():
                return {}

        # Soil Layer
        if any([parameters.get("Soils", None), parameters.get("CurveNumber", None)]):
            ssurgoSoil = SsurgoSoil(
                parameters["aoi"],
                context=context,
                feedback=feedback,
            )
            # Call class method in required sequence
            ssurgoSoil.reprojectTo4326()
            step += 1
            feedback.setCurrentStep(step)
            if feedback.isCanceled():
                return {}

            try:
                ssurgoSoil.postRequest()
                step += 1
                feedback.setCurrentStep(step)
                if feedback.isCanceled():
                    return {}
            except:
                feedback.pushWarning(
                    "Error getting soil data through post request. Your input layer maybe too large. Trying WFS download now.\nIf the Algorithm get stuck during download. Terminate the Algorithm and rerun with a smaller input layer.",
                )
                ssurgoSoil.wfsRequest()
                step += 1
                feedback.setCurrentStep(step)
                if feedback.isCanceled():
                    return {}

                # SSURGO wfs is misconfigured to return x as y and y and x
                ssurgoSoil.swapXY()
                step += 1
                feedback.setCurrentStep(step)
                if feedback.isCanceled():
                    return {}

            ssurgoSoil.fixSoilLayer()
            step += 1
            feedback.setCurrentStep(step)
            if feedback.isCanceled():
                return {}

            ssurgoSoil.clipSoilLayer()
            step += 1
            feedback.setCurrentStep(step)
            if feedback.isCanceled():
                return {}

            outputs["Soils4326"] = ssurgoSoil.soil_layer
            outputs["ReprojectedSoils"] = reprojectLayer(
                outputs["Soils4326"],
                QgsCoordinateReferenceSystem(str(orig_epsg_code)),
                context=context,
                feedback=feedback,
            )
            step += 1
            feedback.setCurrentStep(step)
            if feedback.isCanceled():
                return {}

            # final result
            if parameters.get("Soils", None):
                try:
                    parameters["Soils"].destinationName = "SSURGO Soils"
                except AttributeError:
                    pass
                soils_output = parameters["Soils"]
            else:
                soils_output = QgsProcessing.TEMPORARY_OUTPUT

            results["Soils"] = fixGeometries(
                outputs["ReprojectedSoils"],
                soils_output,
                context=context,
                feedback=feedback,
            )
            step += 1
            feedback.setCurrentStep(step)
            if feedback.isCanceled():
                return {}

        # # Curve Number Calculations
        if parameters.get("CurveNumber", None):

            # Prepare Land Cover for Curve Number Calculation
            # Polygonize (raster to vector)
            outputs["NLCDLandCoverPolygonize"] = gdalPolygonize(
                results["NLCDLandCover"],
                "land_cover",
                context=context,
                feedback=feedback,
            )

            step += 1
            feedback.setCurrentStep(step)
            if feedback.isCanceled():
                return {}

            # Fix geometries
            outputs["NLCDLandCoverVector"] = fixGeometries(
                outputs["NLCDLandCoverPolygonize"],
                context=context,
                feedback=feedback,
            )

            # Prepare Soil for Curve Number Calculation by turning dual soil to single soil
            alg_params = {
                "FIELD_LENGTH": 5,
                "FIELD_NAME": "_hsg_single_",
                "FIELD_PRECISION": 3,
                "FIELD_TYPE": 2,
                "FORMULA": "if( var('drainedsoilsleaveuncheckedifnotsure') = True,replace(\"HYDGRPDCD\", '/D', ''),replace(\"HYDGRPDCD\", map('A/', '', 'B/', '', 'C/', '')))",
                "INPUT": results["Soils"],
                "NEW_FIELD": True,
                "OUTPUT": QgsProcessing.TEMPORARY_OUTPUT,
            }
            outputs["SoilsSingle"] = processing.run(
                "qgis:fieldcalculator",
                alg_params,
                context=context,
                feedback=feedback,
                is_child_algorithm=True,
            )["OUTPUT"]

            curve_number = CurveNumber(
                outputs["NLCDLandCoverVector"],
                outputs["SoilsSingle"],
                parameters["CnLookup"],
                context=context,
                feedback=feedback,
            )

            try:
                parameters["CurveNumber"].destinationName = "Curve Number Layer"
            except AttributeError:
                pass

            results["CurveNumber"], step = curve_number.generateCurveNumber(
                ["MUSYM", "HYDGRPDCD", "MUNAME", "_hsg_single_"],
                ["MUSYM", "MUNAME", "_hsg_single_"],
                'IF ("_hsg_single_" IS NOT NULL, "land_cover" || "_hsg_single_", IF (("MUSYM" = \'W\' OR lower("MUSYM") = \'water\' OR lower("MUNAME") = \'water\' OR "MUNAME" = \'W\'), 11, "land_cover"))',
                start_step=step + 1,
                output=parameters["CurveNumber"],
            )

            step += 1
            feedback.setCurrentStep(step)
            if feedback.isCanceled():
                return {}

        # # log usage
        # with open(cn_log_path, "r+") as f:
        #     counter = int(f.readline())
        #     f.seek(0)
        #     f.write(str(counter + 1))

        # # check if counter is milestone
        # if (counter + 1) % 25 == 0:
        #     appeal_file = NamedTemporaryFile("w", suffix=".html", delete=False)
        #     self.createHTML(appeal_file.name, counter + 1)
        #     results["Message"] = appeal_file.name

        return results

    def name(self):
        """
        Returns the algorithm name, used for identifying the algorithm. This
        string should be fixed for the algorithm, and must not be localised.
        The name should be unique within each provider. Names should contain
        lowercase alphanumeric characters only and no spaces or other
        formatting characters.
        """
        return "CONUS (NLCD & SSURGO)"

    def displayName(self):
        """
        Returns the translated algorithm name, which should be used for any
        user-visible display of the algorithm name.
        """
        return self.tr(self.name())

    def icon(self):
        cmd_folder = os.path.split(inspect.getfile(inspect.currentframe()))[0]
        icon = QIcon(os.path.join(os.path.join(cmd_folder, "icon.png")))
        return icon

    def shortHelpString(self):
        return """<html><body><a "href"="https://github.com/ar-siddiqui/curve_number_generator/wiki/Tutorials">Video Tutorials</a></h3>
<h2>Algorithm description</h2>
<p>This algorithm generates Curve Number layer for the given Area of Interest within the contiguous United States. It can also download Soil, Land Cover, and Impervious Surface datasets for the same area.</p>
<h2>Input parameters</h2>
<h3>Area Boundary</h3>
<p>Area of Interest</p>
<h3>CN_Lookup.csv [optional]</h3>
<p>Optional Table to relate NLCD Land Use Value and HSG Value to a particular curve number. By default the algorithm uses pre defined table. The table must have two columns 'GDCode' and 'CN_Join'. GDCode is concatenation of NLCD Land Use code and Hydrologic Soil Group. <a href="https://raw.githubusercontent.com/ar-siddiqui/curve_number_generator/development/CN_Lookup.csv">Template csv file to create custom table.</a></p>
<h3>Drained Soils? [leave unchecked if not sure]</h3>
<p>Certain Soils are categorized as dual category in SSURGO dataset. They have Hydrologic Soil Group D for Undrained Conditions and Hydrologic Soil Group A/B/C for Drained Conditions.

If left unchecked, the algorithm will assume HSG D for all dual category soils. 

If checked the algorithm will assume HSG A/B/C for each dual category soil.</p>
<h2>Outputs</h2>
<h3>NLCD Land Cover Vector</h3>
<p>NLCD 2019 Land Cover Dataset Vectorized</p>
<h3>NLCD Land Cover Raster</h3>
<p>NLCD 2019 Land Cover Dataset</p>
<h3>NLCD Impervious Surface Raster</h3>
<p>NLCD 2019 Impervious Surface Dataset</p>
<h3>Soil Layer</h3>
<p>SSURGO Extended Soil Dataset </p>
<h3>Curve Number Layer</h3>
<p>Generated Curve Number Layer based on Land Cover and HSG values.</p>
<br><p align="right">Algorithm author: Abdul Raheem Siddiqui</p><p align="right">Help author: Abdul Raheem Siddiqui</p><p align="right">Algorithm version: 1.3</p><p align="right">Contact email: ars.work.ce@gmail.com</p><p>Disclaimer: The curve numbers generated with this algorithm are high level estimates and should be reviewed in detail before being used for detailed modeling or construction projects.</p></body></html>"""

    def createInstance(self):
        return ConusNlcdSsurgo()

    def createHTML(self, outputFile, counter):
        with codecs.open(outputFile, "w", encoding="utf-8") as f:
            f.write(
                f"""
<html>

<head>
    <meta http-equiv="Content-Type" content="text/html;charset=utf-8" />
</head>

<body>
    <p style="font-size:21px;line-height: 1.5;text-align:center;"><br>WOW! You have used the Curve Number Generator
        Plugin <b>{counter}</b>
        times already.<br />If you would like to get any GIS task automated for your organization please contact me at
        ars.work.ce@gmail.com<br />
        If this plugin has saved your time, please consider making a personal or organizational donation of any value to
        the developer.</p>
    <br>
    <form action="https://www.paypal.com/donate" method="post" target="_top" style="text-align: center;">
        <input type="hidden" name="business" value="T25JMRWJAL5SQ" />
        <input type="hidden" name="item_name" value="For Curve Number Generator" />
        <input type="hidden" name="currency_code" value="USD" />
        <input type="image" src="https://www.paypalobjects.com/en_US/i/btn/btn_donateCC_LG.gif" border="0" name="submit"
            title="PayPal - The safer, easier way to pay online!" alt="Donate with PayPal button" />
        <img alt="" border="0" src="https://www.paypal.com/en_US/i/scr/pixel.gif" width="1" height="1" />
    </form>
</body>

</html>"""
            )
