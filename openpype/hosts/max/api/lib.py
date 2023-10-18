# -*- coding: utf-8 -*-
"""Library of functions useful for 3dsmax pipeline."""
import os
import contextlib
import logging
import json
from typing import Any, Dict, Union

import six
from openpype.pipeline import get_current_project_name, colorspace
from openpype.settings import get_project_settings
from openpype.pipeline.context_tools import (
    get_current_project, get_current_project_asset)
from openpype.style import load_stylesheet
from pymxs import runtime as rt


JSON_PREFIX = "JSON::"
log = logging.getLogger("openpype.hosts.max")


def get_main_window():
    """Acquire Max's main window"""
    from qtpy import QtWidgets
    top_widgets = QtWidgets.QApplication.topLevelWidgets()
    name = "QmaxApplicationWindow"
    for widget in top_widgets:
        if (
            widget.inherits("QMainWindow")
            and widget.metaObject().className() == name
        ):
            return widget
    raise RuntimeError('Count not find 3dsMax main window.')


def imprint(node_name: str, data: dict) -> bool:
    node = rt.GetNodeByName(node_name)
    if not node:
        return False

    for k, v in data.items():
        if isinstance(v, (dict, list)):
            rt.SetUserProp(node, k, f"{JSON_PREFIX}{json.dumps(v)}")
        else:
            rt.SetUserProp(node, k, v)

    return True


def lsattr(
        attr: str,
        value: Union[str, None] = None,
        root: Union[str, None] = None) -> list:
    """List nodes having attribute with specified value.

    Args:
        attr (str): Attribute name to match.
        value (str, Optional): Value to match, of omitted, all nodes
            with specified attribute are returned no matter of value.
        root (str, Optional): Root node name. If omitted, scene root is used.

    Returns:
        list of nodes.
    """
    root = rt.RootNode if root is None else rt.GetNodeByName(root)

    def output_node(node, nodes):
        nodes.append(node)
        for child in node.Children:
            output_node(child, nodes)

    nodes = []
    output_node(root, nodes)
    return [
        n for n in nodes
        if rt.GetUserProp(n, attr) == value
    ] if value else [
        n for n in nodes
        if rt.GetUserProp(n, attr)
    ]


def read(container) -> dict:
    data = {}
    props = rt.GetUserPropBuffer(container)
    # this shouldn't happen but let's guard against it anyway
    if not props:
        return data

    for line in props.split("\r\n"):
        try:
            key, value = line.split("=")
        except ValueError:
            # if the line cannot be split we can't really parse it
            continue

        value = value.strip()
        if isinstance(value.strip(), six.string_types) and \
                value.startswith(JSON_PREFIX):
            with contextlib.suppress(json.JSONDecodeError):
                value = json.loads(value[len(JSON_PREFIX):])

        # default value behavior
        # convert maxscript boolean values
        if value == "true":
            value = True
        elif value == "false":
            value = False

        data[key.strip()] = value

    data["instance_node"] = container.Name

    return data


@contextlib.contextmanager
def maintained_selection():
    previous_selection = rt.GetCurrentSelection()
    try:
        yield
    finally:
        if previous_selection:
            rt.Select(previous_selection)
        else:
            rt.Select()


def get_all_children(parent, node_type=None):
    """Handy function to get all the children of a given node

    Args:
        parent (3dsmax Node1): Node to get all children of.
        node_type (None, runtime.class): give class to check for
            e.g. rt.FFDBox/rt.GeometryClass etc.

    Returns:
        list: list of all children of the parent node
    """
    def list_children(node):
        children = []
        for c in node.Children:
            children.append(c)
            children = children + list_children(c)
        return children
    child_list = list_children(parent)

    return ([x for x in child_list if rt.SuperClassOf(x) == node_type]
            if node_type else child_list)


def get_current_renderer():
    """
    Notes:
        Get current renderer for Max

    Returns:
        "{Current Renderer}:{Current Renderer}"
        e.g. "Redshift_Renderer:Redshift_Renderer"
    """
    return rt.renderers.production


def get_default_render_folder(project_setting=None):
    return (project_setting["max"]
                           ["RenderSettings"]
                           ["default_render_image_folder"])


def set_render_frame_range(start_frame, end_frame):
    """
    Note:
        Frame range can be specified in different types. Possible values are:
        * `1` - Single frame.
        * `2` - Active time segment ( animationRange ).
        * `3` - User specified Range.
        * `4` - User specified Frame pickup string (for example `1,3,5-12`).

    Todo:
        Current type is hard-coded, there should be a custom setting for this.
    """
    rt.rendTimeType = 3
    if start_frame is not None and end_frame is not None:
        rt.rendStart = int(start_frame)
        rt.rendEnd = int(end_frame)


def get_multipass_setting(project_setting=None):
    return (project_setting["max"]
                           ["RenderSettings"]
                           ["multipass"])


def set_scene_resolution(width: int, height: int):
    """Set the render resolution

    Args:
        width(int): value of the width
        height(int): value of the height

    Returns:
        None

    """
    # make sure the render dialog is closed
    # for the update of resolution
    # Changing the Render Setup dialog settings should be done
    # with the actual Render Setup dialog in a closed state.
    if rt.renderSceneDialog.isOpen():
        rt.renderSceneDialog.close()

    rt.renderWidth = width
    rt.renderHeight = height


def reset_scene_resolution():
    """Apply the scene resolution from the project definition

    scene resolution can be overwritten by an asset if the asset.data contains
    any information regarding scene resolution .
    Returns:
        None
    """
    data = ["data.resolutionWidth", "data.resolutionHeight"]
    project_resolution = get_current_project(fields=data)
    project_resolution_data = project_resolution["data"]
    asset_resolution = get_current_project_asset(fields=data)
    asset_resolution_data = asset_resolution["data"]
    # Set project resolution
    project_width = int(project_resolution_data.get("resolutionWidth", 1920))
    project_height = int(project_resolution_data.get("resolutionHeight", 1080))
    width = int(asset_resolution_data.get("resolutionWidth", project_width))
    height = int(asset_resolution_data.get("resolutionHeight", project_height))

    set_scene_resolution(width, height)


def get_frame_range() -> Union[Dict[str, Any], None]:
    """Get the current assets frame range and handles.

    Returns:
        dict: with frame start, frame end, handle start, handle end.
    """
    # Set frame start/end
    asset = get_current_project_asset()
    frame_start = asset["data"].get("frameStart")
    frame_end = asset["data"].get("frameEnd")

    if frame_start is None or frame_end is None:
        return

    handle_start = asset["data"].get("handleStart", 0)
    handle_end = asset["data"].get("handleEnd", 0)
    return {
        "frameStart": frame_start,
        "frameEnd": frame_end,
        "handleStart": handle_start,
        "handleEnd": handle_end
    }


def reset_frame_range(fps: bool = True):
    """Set frame range to current asset.
    This is part of 3dsmax documentation:

    animationRange: A System Global variable which lets you get and
        set an Interval value that defines the start and end frames
        of the Active Time Segment.
    frameRate: A System Global variable which lets you get
            and set an Integer value that defines the current
            scene frame rate in frames-per-second.
    """
    if fps:
        data_fps = get_current_project(fields=["data.fps"])
        fps_number = float(data_fps["data"]["fps"])
        rt.frameRate = fps_number
    frame_range = get_frame_range()
    frame_start_handle = frame_range["frameStart"] - int(
        frame_range["handleStart"]
    )
    frame_end_handle = frame_range["frameEnd"] + int(frame_range["handleEnd"])
    set_timeline(frame_start_handle, frame_end_handle)
    set_render_frame_range(frame_start_handle, frame_end_handle)


def set_context_setting():
    """Apply the project settings from the project definition

    Settings can be overwritten by an asset if the asset.data contains
    any information regarding those settings.

    Examples of settings:
        frame range
        resolution

    Returns:
        None
    """
    reset_scene_resolution()
    reset_frame_range()
    reset_colorspace()


def get_max_version():
    """
    Args:
    get max version date for deadline

    Returns:
        #(25000, 62, 0, 25, 0, 0, 997, 2023, "")
        max_info[7] = max version date
    """
    max_info = rt.MaxVersion()
    return max_info[7]


def is_headless():
    """Check if 3dsMax runs in batch mode.
    If it returns True, it runs in 3dsbatch.exe
    If it returns False, it runs in 3dsmax.exe
    """
    return rt.maxops.isInNonInteractiveMode()


@contextlib.contextmanager
def viewport_camera(camera):
    """Function to set viewport camera during context
    ***For 3dsMax 2024+
    Args:
        camera (str): viewport camera for review render
    """
    original = rt.viewport.getCamera()
    has_autoplay = rt.preferences.playPreviewWhenDone
    if not original:
        # if there is no original camera
        # use the current camera as original
        original = rt.getNodeByName(camera)
    review_camera = rt.getNodeByName(camera)
    try:
        rt.viewport.setCamera(review_camera)
        rt.preferences.playPreviewWhenDone = False
        yield
    finally:
        rt.viewport.setCamera(original)
        rt.preferences.playPreviewWhenDone = has_autoplay


@contextlib.contextmanager
def viewport_preference_setting(camera,
                                general_viewport,
                                nitrous_viewport,
                                vp_button_mgr,
                                preview_preferences):
    original_camera = rt.viewport.getCamera()
    if not original_camera:
        # if there is no original camera
        # use the current camera as original
        original_camera = rt.getNodeByName(camera)
    review_camera = rt.getNodeByName(camera)
    orig_vp_grid = rt.viewport.getGridVisibility(1)
    orig_vp_bkg = rt.viewport.IsSolidBackgroundColorMode()

    nitrousGraphicMgr = rt.NitrousGraphicsManager
    viewport_setting = nitrousGraphicMgr.GetActiveViewportSetting()
    vp_button_mgr_original = {
        key: getattr(rt.ViewportButtonMgr, key) for key in vp_button_mgr
    }
    nitrous_viewport_original = {
        key: getattr(viewport_setting, key) for key in nitrous_viewport
    }
    preview_preferences_original = {
        key: getattr(rt.preferences, key) for key in preview_preferences
    }
    try:
        rt.viewport.setCamera(review_camera)
        rt.viewport.setGridVisibility(1, general_viewport["dspGrid"])
        rt.viewport.EnableSolidBackgroundColorMode(general_viewport["dspBkg"])
        for key, value in vp_button_mgr.items():
            setattr(rt.ViewportButtonMgr, key, value)
        for key, value in nitrous_viewport.items():
            if nitrous_viewport[key] != nitrous_viewport_original[key]:
                setattr(viewport_setting, key, value)
        for key, value in preview_preferences.items():
            setattr(rt.preferences, key, value)
        yield

    finally:
        rt.viewport.setCamera(review_camera)
        rt.viewport.setGridVisibility(1, orig_vp_grid)
        rt.viewport.EnableSolidBackgroundColorMode(orig_vp_bkg)
        for key, value in vp_button_mgr_original.items():
            setattr(rt.ViewportButtonMgr, key, value)
        for key, value in nitrous_viewport_original.items():
            setattr(viewport_setting, key, value)
        for key, value in preview_preferences_original.items():
            setattr(rt.preferences, key, value)
        rt.completeRedraw()


def set_timeline(frameStart, frameEnd):
    """Set frame range for timeline editor in Max
    """
    rt.animationRange = rt.interval(frameStart, frameEnd)
    return rt.animationRange


def reset_colorspace():
    """OCIO Configuration
    Supports in 3dsMax 2024+

    """
    if int(get_max_version()) < 2024:
        return
    project_name = get_current_project_name()
    colorspace_mgr = rt.ColorPipelineMgr
    project_settings = get_project_settings(project_name)

    max_config_data = colorspace.get_imageio_config(
        project_name, "max", project_settings)
    if max_config_data:
        ocio_config_path = max_config_data["path"]
        colorspace_mgr = rt.ColorPipelineMgr
        colorspace_mgr.Mode = rt.Name("OCIO_Custom")
        colorspace_mgr.OCIOConfigPath = ocio_config_path

    colorspace_mgr.OCIOConfigPath = ocio_config_path


def check_colorspace():
    parent = get_main_window()
    if parent is None:
        log.info("Skipping outdated pop-up "
                 "because Max main window can't be found.")
    if int(get_max_version()) >= 2024:
        color_mgr = rt.ColorPipelineMgr
        project_name = get_current_project_name()
        project_settings = get_project_settings(project_name)
        max_config_data = colorspace.get_imageio_config(
            project_name, "max", project_settings)
        if max_config_data and color_mgr.Mode != rt.Name("OCIO_Custom"):
            if not is_headless():
                from openpype.widgets import popup
                dialog = popup.Popup(parent=parent)
                dialog.setWindowTitle("Warning: Wrong OCIO Mode")
                dialog.setMessage("This scene has wrong OCIO "
                                  "Mode setting.")
                dialog.setButtonText("Fix")
                dialog.setStyleSheet(load_stylesheet())
                dialog.on_clicked.connect(reset_colorspace)
                dialog.show()

def unique_namespace(namespace, format="%02d",
                     prefix="", suffix="", con_suffix="CON"):
    """Return unique namespace

    Arguments:
        namespace (str): Name of namespace to consider
        format (str, optional): Formatting of the given iteration number
        suffix (str, optional): Only consider namespaces with this suffix.
        con_suffix: max only, for finding the name of the master container

    >>> unique_namespace("bar")
    # bar01
    >>> unique_namespace(":hello")
    # :hello01
    >>> unique_namespace("bar:", suffix="_NS")
    # bar01_NS:

    """

    def current_namespace():
        current = namespace
        # When inside a namespace Max adds no trailing :
        if not current.endswith(":"):
            current += ":"
        return current

    # Always check against the absolute namespace root
    # There's no clash with :x if we're defining namespace :a:x
    ROOT = ":" if namespace.startswith(":") else current_namespace()

    # Strip trailing `:` tokens since we might want to add a suffix
    start = ":" if namespace.startswith(":") else ""
    end = ":" if namespace.endswith(":") else ""
    namespace = namespace.strip(":")
    if ":" in namespace:
        # Split off any nesting that we don't uniqify anyway.
        parents, namespace = namespace.rsplit(":", 1)
        start += parents + ":"
        ROOT += start

    iteration = 1
    increment_version = True
    while increment_version:
        nr_namespace = namespace + format % iteration
        unique = prefix + nr_namespace + suffix
        container_name = f"{unique}:{namespace}{con_suffix}"
        if not rt.getNodeByName(container_name):
            name_space = start + unique + end
            increment_version = False
            return name_space
        else:
            increment_version = True
        iteration += 1


def get_namespace(container_name):
    """Get the namespace and name of the sub-container

    Args:
        container_name (str): the name of master container

    Raises:
        RuntimeError: when there is no master container found

    Returns:
        namespace (str): namespace of the sub-container
        name (str): name of the sub-container
    """
    node = rt.getNodeByName(container_name)
    if not node:
        raise RuntimeError("Master Container Not Found..")
    name = rt.getUserProp(node, "name")
    namespace = rt.getUserProp(node, "namespace")
    return namespace, name


def object_transform_set(container_children):
    """A function which allows to store the transform of
    previous loaded object(s)
    Args:
        container_children(list): A list of nodes

    Returns:
        transform_set (dict): A dict with all transform data of
        the previous loaded object(s)
    """
    transform_set = {}
    for node in container_children:
        name = f"{node.name}.transform"
        transform_set[name] = node.pos
        name = f"{node.name}.scale"
        transform_set[name] = node.scale
    return transform_set


def get_plugins() -> list:
    """Get all loaded plugins in 3dsMax

    Returns:
        plugin_info_list: a list of loaded plugins
    """
    manager = rt.PluginManager
    count = manager.pluginDllCount
    plugin_info_list = []
    for p in range(1, count + 1):
        plugin_info = manager.pluginDllName(p)
        plugin_info_list.append(plugin_info)

    return plugin_info_list


def publish_review_animation(instance, filepath,
                             start, end, fps):
    """Function to set up preview arguments in MaxScript.
    ****For 3dsMax 2024+

    Args:
        instance (str): instance
        filepath (str): output of the preview animation
        start (int): startFrame
        end (int): endFrame
        fps (float): fps value

    Returns:
        list: job arguments
    """
    job_args = list()
    default_option = f'CreatePreview filename:"{filepath}"'
    job_args.append(default_option)
    frame_option = f"outputAVI:false start:{start} end:{end} fps:{fps}" # noqa
    job_args.append(frame_option)
    options = [
        "percentSize", "dspGeometry", "dspShapes",
        "dspLights", "dspCameras", "dspHelpers", "dspParticles",
        "dspBones", "dspBkg", "dspGrid", "dspSafeFrame", "dspFrameNums"
    ]

    for key in options:
        enabled = instance.data.get(key)
        if enabled:
            job_args.append(f"{key}:{enabled}")

    visual_style_preset = instance.data.get("visualStyleMode")
    if visual_style_preset == "Realistic":
        visual_style_preset = "defaultshading"
    else:
        visual_style_preset = visual_style_preset.lower()
    # new argument exposed for Max 2024 for visual style
    visual_style_option = f"vpStyle:#{visual_style_preset}"
    job_args.append(visual_style_option)
    # new argument for pre-view preset exposed in Max 2024
    preview_preset = instance.data.get("viewportPreset")
    if preview_preset == "Quality":
        preview_preset = "highquality"
    elif preview_preset == "Customize":
        preview_preset = "userdefined"
    else:
        preview_preset = preview_preset.lower()
    preview_preset_option = f"vpPreset:#{preview_preset}"
    job_args.append(preview_preset_option)
    viewport_texture = instance.data.get("vpTexture", True)
    if viewport_texture:
        viewport_texture_option = f"vpTexture:{viewport_texture}"
        job_args.append(viewport_texture_option)

    job_str = " ".join(job_args)
    log.debug(job_str)

    return job_str


def publish_preview_sequences(staging_dir, filename,
                              startFrame, endFrame,
                              percentSize, ext):
    """publish preview animation by creating bitmaps
    ***For 3dsMax Version <2024

    Args:
        staging_dir (str): staging directory
        filename (str): filename
        startFrame (int): start frame
        endFrame (int): end frame
        percentSize (int): percentage of the resolution
        ext (str): image extension
    """
    # get the screenshot
    rt.forceCompleteRedraw()
    rt.enableSceneRedraw()
    resolution_percentage = float(percentSize) / 100
    res_width = rt.renderWidth * resolution_percentage
    res_height = rt.renderHeight * resolution_percentage

    viewportRatio = float(res_width / res_height)

    for i in range(startFrame, endFrame + 1):
        rt.sliderTime = i
        fname = "{}.{:04}.{}".format(filename, i, ext)
        filepath = os.path.join(staging_dir, fname)
        filepath = filepath.replace("\\", "/")
        preview_res = rt.bitmap(
            res_width, res_height, filename=filepath)
        dib = rt.gw.getViewportDib()
        dib_width = float(dib.width)
        dib_height = float(dib.height)
        renderRatio = float(dib_width / dib_height)
        if viewportRatio <= renderRatio:
            heightCrop = (dib_width / renderRatio)
            topEdge = int((dib_height - heightCrop) / 2.0)
            tempImage_bmp = rt.bitmap(dib_width, heightCrop)
            src_box_value = rt.Box2(0, topEdge, dib_width, heightCrop)
        else:
            widthCrop = dib_height * renderRatio
            leftEdge = int((dib_width - widthCrop) / 2.0)
            tempImage_bmp = rt.bitmap(widthCrop, dib_height)
            src_box_value = rt.Box2(0, leftEdge, dib_width, dib_height)
        rt.pasteBitmap(dib, tempImage_bmp, src_box_value, rt.Point2(0, 0))

        # copy the bitmap and close it
        rt.copy(tempImage_bmp, preview_res)
        rt.close(tempImage_bmp)

        rt.save(preview_res)
        rt.close(preview_res)

        rt.close(dib)

        if rt.keyboard.escPressed:
            rt.exit()
    # clean up the cache
    rt.gc(delayed=True)
