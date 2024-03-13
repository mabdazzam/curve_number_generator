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
        email                : ars.work.ce@gmail.com
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
from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsProcessing,
    QgsProcessingMultiStepFeedback,
    QgsProcessingParameterBoolean,
    QgsProcessingParameterDefinition,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterRasterDestination,
    QgsProcessingParameterVectorDestination,
    QgsProcessingParameterVectorLayer,
    QgsUnitTypes,
    QgsVectorLayer,
)
from qgis.PyQt.QtGui import QIcon

from curve_number_generator.processing.algorithms.conus_nlcd_ssurgo.ssurgo_soil import (
    SsurgoSoil,
)
from curve_number_generator.processing.config import CONUS_NLCD_SSURGO, PLUGIN_VERSION
from curve_number_generator.processing.curve_number_generator_algorithm import (
    CurveNumberGeneratorAlgorithm,
)
from curve_number_generator.processing.tools.curve_numper import CurveNumber
from curve_number_generator.processing.tools.utils import (
    checkAreaLimits,
    createDefaultLookup,
    createRequestBBOXDim,
    downloadFile,
    fixGeometries,
    gdalPolygonize,
    gdalWarp,
    getAndUpdateMessage,
    getExtent,
    getExtentArea,
    reprojectLayer,
)

cmd_folder = os.path.split(inspect.getfile(inspect.currentframe()))[0]
if cmd_folder not in sys.path:
    sys.path.insert(0, cmd_folder)

__author__ = "Abdul Raheem Siddiqui"
__date__ = "2022-07-22"
__copyright__ = "(C) 2022 by Abdul Raheem Siddiqui"

# This will get replaced with a git SHA1 when you do a git archive

__revision__ = "$Format:%H$"


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
            "DrainedSoils",
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
                createByDefault=True,
                defaultValue=None,
            )
        )

    def processAlgorithm(self, parameters, context, model_feedback):
        # Use a multi-step feedback, so that individual child algorithm progress reports are adjusted for the
        # overall progress through the model
        feedback = QgsProcessingMultiStepFeedback(19, model_feedback)
        results = {}
        outputs = {}

        # Assiging Default CN_Lookup Table
        if not parameters.get("CnLookup", None):
            parameters["CnLookup"] = createDefaultLookup(cmd_folder)

        area_layer = self.parameterAsVectorLayer(parameters, "aoi", context)
        orig_epsg_code = area_layer.crs().authid()  # preserve orignal epsg_code to project back to it

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
        # add a buffer cell on each side, refer to #49 for reasoning
        extent = (extent[0] - 30, extent[1] - 30, extent[2] + 30, extent[3] + 30)
        bbox_dim = createRequestBBOXDim(extent, 30)

        # NLCD Impervious Raster
        if parameters.get("NLCDImpervious", None):
            outputs["DownloadNlcdImp"] = downloadFile(
                CONUS_NLCD_SSURGO["NLCD_IMP_2021"].format(
                    epsg_code,
                    bbox_dim[0],
                    bbox_dim[1],
                    ",".join([str(item) for item in extent]),
                ),
                "https://www.mrlc.gov/geoserver/mrlc_display/NLCD_2021_Impervious_L48/ows",
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

            imp_style_path = os.path.join(cmd_folder, "nlcd_impervious.qml")
            self.handle_post_processing(results["NLCDImpervious"], imp_style_path, context)

        # NLCD Land Cover Data
        if any([parameters.get("NLCDLandCover", None), parameters.get("CurveNumber", None)]):
            outputs["DownloadNlcdLC"] = downloadFile(
                CONUS_NLCD_SSURGO["NLCD_LC_2021"].format(
                    epsg_code,
                    bbox_dim[0],
                    bbox_dim[1],
                    ",".join([str(item) for item in extent]),
                ),
                "https://www.mrlc.gov/geoserver/mrlc_display/NLCD_2021_Land_Cover_L48/ows",
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
            outputs["NLCDLandCover"] = gdalWarp(
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

            if parameters.get("NLCDLandCover", None):
                lc_style_path = os.path.join(cmd_folder, "nlcd_land_cover.qml")
                results["NLCDLandCover"] = outputs["NLCDLandCover"]
                self.handle_post_processing(results["NLCDLandCover"], lc_style_path, context)

        # Soil Layer
        if any([parameters.get("Soils", None), parameters.get("CurveNumber", None)]):
            ssurgoSoil = SsurgoSoil(parameters["aoi"], context=context, feedback=feedback)
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
                    "Error getting soil data through post request. Your input layer maybe too large. Trying WFS download now.\nIf the Algorithm get stuck during download. Terminate the Algorithm and rerun with a smaller input layer."
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

            outputs["Soils"] = fixGeometries(
                outputs["ReprojectedSoils"],
                soils_output,
                context=context,
                feedback=feedback,
            )
            step += 1
            feedback.setCurrentStep(step)
            if feedback.isCanceled():
                return {}

            if parameters.get("Soils", None):
                soils_style_path = os.path.join(cmd_folder, "soils.qml")
                results["Soils"] = outputs["Soils"]
                self.handle_post_processing(results["Soils"], soils_style_path, context)

        # # Curve Number Calculations
        if parameters.get("CurveNumber", None):
            # Prepare Land Cover for Curve Number Calculation
            # Polygonize (raster to vector)
            outputs["NLCDLandCoverPolygonize"] = gdalPolygonize(
                outputs["NLCDLandCover"],
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
                outputs["NLCDLandCoverPolygonize"], context=context, feedback=feedback
            )

            # Prepare Soil for Curve Number Calculation by turning dual soil to single soil
            if parameters["DrainedSoils"]:
                single_soil_formula = "replace(\"HYDGRPDCD\", '/D', '')"
            else:
                single_soil_formula = "replace(\"HYDGRPDCD\", map('A/', '', 'B/', '', 'C/', ''))"
            alg_params = {
                "FIELD_LENGTH": 5,
                "FIELD_NAME": "_hsg_single_",
                "FIELD_PRECISION": 3,
                "FIELD_TYPE": 2,
                "FORMULA": single_soil_formula,
                "INPUT": outputs["Soils"],
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
                parameters["CurveNumber"].destinationName = "Curve Number"
            except AttributeError:
                pass

            results["CurveNumber"], step = curve_number.generateCurveNumber(
                ["MUSYM", "HYDGRPDCD", "MUNAME", "_hsg_single_"],
                ["MUSYM", "MUNAME", "_hsg_single_"],
                'IF ("_hsg_single_" IS NOT NULL, "land_cover" || \'_\' ||  "_hsg_single_", IF (("MUSYM" = \'W\' OR lower("MUSYM") = \'water\' OR lower("MUNAME") = \'water\' OR "MUNAME" = \'W\'), \'11_\', "land_cover" || \'_\'))',
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
        return "conusnlcdssurgo"

    def displayName(self):
        """
        Returns the translated algorithm name, which should be used for any
        user-visible display of the algorithm name.
        """
        return self.tr("Curve Number Generator (CONUS) (NLCD & SSURGO)")

    def icon(self):
        icon = QIcon(os.path.join(cmd_folder, "icon.png"))
        return icon

    def shortHelpString(self):
        msg = ""
        try:
            msg = getAndUpdateMessage()
        except Exception as e:
            print(e)

        return (
            msg
            + f"""<html><body><a "href"="https://github.com/ar-siddiqui/curve_number_generator/wiki/Tutorials#curve-number-generator-conus-nlcd--ssurgo">Video Tutorial</a></h3>
<h2>Algorithm description</h2>
<p>This algorithm generates Curve Number layer for the given Area of Interest within the contiguous United States. It can also download Soil, Land Cover, and Impervious Surface datasets for the same area.</p>
<h2>Input parameters</h2>
<h3>Area of Interest</h3>
<p>Polygon layer representing area of interest</p>
<h3>Lookup Table [optional]</h3>
<p>Optional Table to relate NLCD Land Use Value and HSG Value to a particular curve number. By default the algorithm uses pre defined table. The table must have two columns 'grid_code' and 'cn'. grid_code is concatenation of NLCD Land Use code and Hydrologic Soil Group. <a href="https://raw.githubusercontent.com/ar-siddiqui/curve_number_generator/v{PLUGIN_VERSION}/curve_number_generator/processing/algorithms/conus_nlcd_ssurgo/default_lookup.csv">Template csv file to create custom table</a> (add an optional <a href="https://raw.githubusercontent.com/ar-siddiqui/curve_number_generator/v{PLUGIN_VERSION}/curve_number_generator/processing/algorithms/conus_nlcd_ssurgo/default_lookup.csvt">`.csvt`</a> file to control column data types).</p>
<h3>Drained Soils? [leave unchecked if not sure]</h3>
<p>Certain Soils are categorized as dual category in SSURGO dataset. They have Hydrologic Soil Group D for Undrained Conditions and Hydrologic Soil Group A/B/C for Drained Conditions.

If left unchecked, the algorithm will assume HSG D for all dual category soils.

If checked the algorithm will assume HSG A/B/C for each dual category soil.</p>
<h2>Outputs</h2>
<h3>NLCD Land Cover</h3>
<p>NLCD 2021 Land Cover Raster</p>
<h3>NLCD Impervious Surface</h3>
<p>NLCD 2021 Impervious Surface Raster</p>
<h3>Soils</h3>
<p>SSURGO Extended Soil Dataset </p>
<h3>Curve Number</h3>
<p>Generated Curve Number Layer based on Land Cover and HSG values.</p>
<br><p align="right">Algorithm author: Abdul Raheem Siddiqui</p><p align="right">Help author: Abdul Raheem Siddiqui</p><p align="right">Algorithm version: {PLUGIN_VERSION}</p><p align="right">Contact email: ars.work.ce@gmail.com</p><p>Disclaimer: The curve numbers generated with this algorithm are high level estimates and should be reviewed in detail before being used for detailed modeling or construction projects.</p></body></html>"""
        )

    def createInstance(self):
        return ConusNlcdSsurgo()
