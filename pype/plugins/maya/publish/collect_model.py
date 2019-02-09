from maya import cmds

import pyblish.api


class CollectModelData(pyblish.api.InstancePlugin):
    """Collect model data

    Ensures always only a single frame is extracted (current frame).

    Note:
        This is a workaround so that the `pype.model` family can use the
        same pointcache extractor implementation as animation and pointcaches.
        This always enforces the "current" frame to be published.

    """

    order = pyblish.api.CollectorOrder + 0.499
    label = 'Collect Model Data'
    families = ["model"]

    def process(self, instance):
        # Extract only current frame (override)
        frame = cmds.currentTime(query=True)
        instance.data['startFrame'] = frame
        instance.data['endFrame'] = frame

        # make ftrack publishable
        if instance.data.get('families'):
            instance.data['families'].append('ftrack')
        else:
            instance.data['families'] = ['ftrack']
