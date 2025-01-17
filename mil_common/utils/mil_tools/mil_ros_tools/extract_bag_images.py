#!/usr/bin/env python3
"""
Extracts images from several bag files according to a YAML configuration.

Designed to create datasets used on labelbox.io for image segmentation / classification
projects used for perception on mil robots.

Usage:
rosrun mil_tools extract_bag_images config.yaml --source-dir <location of bag files> --image-dir <directory for extracted images>         # noqa

See example_bag_image_config.yaml or the class documentation for how to form this configuration.
Essentially, the yaml file defines a project, which is a single labeling task or project on labelbox.io.
Each project contains n datasets. Each dataset has a list of bags (sources) to get images from and represents a dataset on labelbox.io.
"""

import argparse
import os
from typing import Optional

import cv2
import rosbag
import rospy
import yaml
from cv_bridge.boost.cv_bridge_boost import cvtColor2
from genpy import Time
from image_geometry import PinholeCameraModel
from mil_tools import slugify
from mil_vision_tools.image_proc import ImageProc, ImageSet


class BagImageExtractorSource:
    """
    Provides functionality to extract a set of images from a single bag file according to the configuration.

    Used primarily by :class:`BagImageExtractorProject`.
    """

    MONO = "mono"
    COLOR = "color"
    RECT = "rect"
    RECT_COLOR = "rect_color"
    RAW = "raw"

    def __init__(
        self,
        filename: str,
        topic: str,
        start: Optional[Time] = None,
        stop: Optional[Time] = None,
        freq: Optional[int] = None,
        encoding: Optional["BagImageExtractorSource"] = None,
    ):
        """
        Args:
            filename (str): Name of bag file. Can be an absolute path, or
                will be resolved relative to specified dir when
                topic (str): Topic in the bag file with the images you wish to extract
                start (Optional[genpy.Time]): Time relative to start of bag to
                begin extracting images from. If None, extraction will start at beginning of bag
                stop (Optional[genpy.Time]): time relative to start of bag to stop
                extracting images from. If None, extraction will end at end of bag.
                freq (Optional[int]): Number of images to extract for each second
                of bag time. If None, include all images.
                encoding (Optional[BagImageExtractorSource]): Specifies if color conversion
                or distortion rectification should be applied. If None, images
                will be saved in the same format they are in the specified topic.
                If 'mono', image will be converted to grayscale from color
                or bayer image. If 'color', image will be converted to color from bayer.
                If 'rect', image will be converted to grayscale and rectified
                using camera info. If 'rect_color', image will be converted to
                color and rectified using camera info
        """
        self.filename = filename
        self.topic = topic
        self.start = start
        self.stop = stop
        self.freq = freq
        self.encoding = self.get_image_proc_flags_from_encoding(encoding)
        self.image_set = ImageSet()

    @classmethod
    def get_image_proc_flags_from_encoding(cls, encoding):
        """
        Returns the flag to pass to mil image proc based on encoding string.

        Args:
          encoding:

        Returns:

        """
        if encoding is None or encoding == cls.RAW:
            return ImageProc.RAW
        elif encoding == cls.MONO:
            return ImageProc.MONO
        elif encoding == cls.RECT:
            return ImageProc.RECT
        elif encoding == cls.COLOR:
            return ImageProc.COLOR
        elif encoding == cls.RECT_COLOR:
            return ImageProc.RECT_COLOR
        else:
            raise Exception(f"invalid encoding {encoding}")

    @classmethod
    def from_dict(cls, d: dict):
        """
        Creates source config from a dictionary, such as from a YAML file.
        Must at a minimum have a file, and topic. Can also have start,
        stop, encoding, and freq to change the configuration described in the __init__
        { 'file': 'example.bag', 'topic': '/camera/image_raw', }

        Args:
          d: dict - The dict to construct the object from

        Returns:

        """
        if not isinstance(d, dict):
            raise Exception("must be dict")
        if "file" not in d:
            raise Exception("dict must contain a file")
        if "topic" not in d:
            raise Exception("dict must contain a topic")
        return cls(
            d["file"],
            d["topic"],
            start=d.get("start"),
            stop=d.get("stop"),
            freq=d.get("freq"),
            encoding=d.get("encoding"),
        )

    @staticmethod
    def get_camera_model(bag: str, topic: str):
        """
        Gets the PinholeCameraModel object given a bag and a image topic, by
        getting the first camera_info message in the same namespace.

        Args:
          bag: str
          topic: str

        Returns:

        """
        topic_root = topic.rsplit("/", 1)[0]
        camera_info_topic = topic_root + "/" + "camera_info"
        try:
            _, msg, _ = next(bag.read_messages(topics=camera_info_topic))
        except StopIteration:
            raise Exception(
                f"no camera info messages found on topic {camera_info_topic} in {bag}",
            )
        if msg._type != "sensor_msgs/CameraInfo":
            raise Exception(
                f"msg on topic {camera_info_topic} are not camera info in bag {bag}",
            )
        model = PinholeCameraModel()
        model.fromCameraInfo(msg)
        return model

    def _save_img(self, msg, time, image_dir, prefix=""):
        """Save the image msg to the image directory, named with the time object
        converted to a string. Uses mil image proc to rectify / convert color as
        configured (see __init__)

        Args:
          msg:
          time:
          image_dir:
          prefix:  (Default value = "")

        Returns:

        """
        ImageProc.process(msg, self.camera_model, self.image_set, self.encoding)
        if self.encoding == 0:
            img = self.image_set.raw
        elif self.encoding == ImageProc.MONO:
            img = self.image_set.mono
        elif self.encoding == ImageProc.RECT:
            img = self.image_set.rect
        elif self.encoding == ImageProc.COLOR:
            img = self.image_set.color
        elif self.encoding == ImageProc.RECT_COLOR:
            img = self.image_set.rect_color

        if self.encoding == ImageProc.RAW:
            img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)

        # If color, convert to bgr
        if self.encoding == ImageProc.COLOR or self.encoding == ImageProc.RECT_COLOR:
            img = cvtColor2(img, self.image_set.color_encoding, "bgr8")

        # Uncomment this is bag is recorded in BGR format so images don't appear inverted
        # img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        filename = os.path.join(image_dir, prefix + str(msg.header.stamp) + ".png")
        cv2.imwrite(filename, img)

    def extract_images(self, source_dir=".", image_dir=".", verbose=False):
        """Extract the images using the configuration from __init__, resolving the bag file
        relative to source_dir and placing extracted images into image_dir.

        Args:
          source_dir:  (Default value = ".")
          image_dir:  (Default value = ".")
          verbose:  (Default value = False)

        Returns:

        """
        if verbose:
            print(
                f"\tExtracting images from topic {self.topic} in {self.filename}",
            )
        filename = os.path.join(source_dir, self.filename)
        b = rosbag.Bag(filename)
        if self.encoding != 0:
            self.camera_model = self.get_camera_model(b, self.topic)
        else:
            self.camera_model = None
        _, _, first_time = next(b.read_messages())
        start = first_time + rospy.Duration(self.start) if self.start else first_time
        stop = first_time + rospy.Duration(self.stop) if self.stop else None
        interval = rospy.Duration(1.0 / self.freq) if self.freq else rospy.Duration(0)
        next_time = start
        prefix = slugify(str(self.filename)) + "_" + slugify(str(self.topic))
        for _, msg, time in b.read_messages(
            topics=self.topic,
            start_time=start,
            end_time=stop,
        ):
            if time >= next_time:
                next_time = time + interval
                self._save_img(msg, time, image_dir, prefix=prefix)


class BagImageExtractorDatasets:
    """Represents a dataset, or a set of bags from which images will be
    extracted and put into the same directory. For example, a set of bags
    containing a particular challenge from the same day.

    Args:

    Returns:

    """

    def __init__(self, name, sources):
        """
        @param name: the name of this dataset (string), will be used to write extracted images to
                     a directory with this name.
        @param sources: a list of BagImageExtractorSource instances making up the dataset.
                        When extract_images is called, images will be extracted from each of these sources
                        into the same directory.
        """
        self.name = name
        self.sources = sources

    @classmethod
    def from_dict(cls, d):
        """Construct from a dictionary, as in from a yaml file. Must have a name key
        and a sources which maps to a list of dictionaries in the form described in BagImageExtractorSource.from_dict.
        ex:
        { 'name': 'scanthecode_day1',
          'sources': [
             {'file': 'a.bag', 'topic':'/camera/image_raw', ...},
             {'file': 'b.bag', ...}
          ]
        }

        Args:
          d:

        Returns:

        """
        if not isinstance(d, dict):
            raise Exception("must be dict")
        if "name" not in d:
            raise Exception("dict must contain a name")
        if "sources" not in d:
            raise Exception("yaml must contain a list of sources. See example.")
        sources = []
        for source in d["sources"]:
            sources.append(BagImageExtractorSource.from_dict(source))
        return cls(d["name"], sources)

    def extract_images(self, source_dir=".", image_dir=".", verbose=False):
        """Extract images from each source bag in this dataset into a single
        directory.

        Args:
          source_dir: the directory from which the sources' filenames will be
        resolved relative to. (Default value = ".")
          image_dir: directory in which to create the directory will extracted images will go.
        For example, if image_dir='/home/user/images' and this instances
        was created with name='scanthecode_day1', images will go into
        /home/user/images/scanthecode_day1 (Default value = ".")
          verbose:  (Default value = False)

        Returns:

        """
        if verbose:
            print(f"Producing dataset '{self.name}'")
        image_dir = os.path.join(image_dir, self.name)
        if not os.path.isdir(image_dir):
            if os.path.exists(image_dir):
                raise Exception(f"{image_dir} exists but is not a directory")
            os.makedirs(image_dir)
        for source in self.sources:
            source.extract_images(
                source_dir=source_dir,
                image_dir=image_dir,
                verbose=verbose,
            )


class BagImageExtractorProject:
    """Holds the configuration for a list of datasets, forming one logical
    project for labeling. For example, a user may create a project
    for the labeling buoys, which contains 3 datasets each with
    bags from different test days.

    Args:

    Returns:

    """

    def __init__(self, datasets, source_dir=".", image_dir="."):
        """
        @param datasets: a list of BagImageExtractorDatasets forming this project
        @param source_dir: directory from which source bag filenames will be resolved relative to.
        @param image_dir: directory in which to put extracted images. Each dataset will be given its
                          own directory within image_dir.
        """
        source_dir = "." if source_dir is None else source_dir
        image_dir = "." if image_dir is None else image_dir
        self.datasets = datasets
        self.source_dir = source_dir
        self.image_dir = image_dir

    @classmethod
    def from_dict(cls, d):
        """Create a project from a dictionary, like when parsed from YAML file.

        Args:
          d:

        Returns:

        """
        if not isinstance(d, dict):
            raise Exception("must be dict")
        if "datasets" not in d:
            raise Exception("dict must contain a list of datasets")
        datasets = []
        for dataset in d["datasets"]:
            datasets.append(BagImageExtractorDatasets.from_dict(dataset))
        return cls(
            datasets,
            source_dir=d.get("source_dir"),
            image_dir=d.get("image_dir"),
        )

    def extract_images(self, verbose=False):
        """

        Args:
          verbose:  (Default value = False)

        Returns:

        """
        for dataset in self.datasets:
            dataset.extract_images(
                source_dir=self.source_dir,
                image_dir=self.image_dir,
                verbose=verbose,
            )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Extracts images from ROS bags into image files according to a configuration.\n\
                     Designed to be used to create labelbox.io projects for segmentation/classification.",
    )
    parser.add_argument(
        "config",
        type=str,
        help="YAML file specifying what bags to read and extract images from.\
                              See example YAML for details",
    )
    parser.add_argument(
        "--source-dir",
        "-s",
        dest="source_dir",
        type=str,
        default=None,
        help="directory to resolve relative paths specified in YAML for input bags. \n\
                              Defaults to current directory.",
    )
    parser.add_argument(
        "--image-dir",
        "-o",
        dest="image_dir",
        type=str,
        default=None,
        help="directory to resolve relative paths specified in YAML for output (labeled) bags. \n\
                              Defaults to current directory.",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Print status info along the way",
    )
    args = parser.parse_args()

    # Load config from yaml file specified
    config_file = open(args.config)
    config = yaml.load(config_file, Loader=yaml.Loader)
    if not isinstance(config, dict):
        raise Exception("yaml config should be in dictionary format. See example")

    # Set bag_dir and image_dir from cli args or yaml config or default
    if args.source_dir is not None:
        config["source_dir"] = args.source_dir
    if args.image_dir is not None:
        config["image_dir"] = args.image_dir

    # Construct a project from the config and extract images
    project = BagImageExtractorProject.from_dict(config)
    project.extract_images(verbose=args.verbose)
