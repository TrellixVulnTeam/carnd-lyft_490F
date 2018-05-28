import re
import random
import numpy as np
import os.path
import cv2
import scipy.misc
import shutil
import zipfile
import time
import tensorflow as tf
from glob import glob
from urllib.request import urlretrieve
from tqdm import tqdm


LIMIT = 10

class DLProgress(tqdm):
    last_block = 0

    def hook(self, block_num=1, block_size=1, total_size=None):
        self.total = total_size
        self.update((block_num - self.last_block) * block_size)
        self.last_block = block_num


def maybe_download_pretrained_vgg(data_dir):
    """
    Download and extract pretrained vgg model if it doesn't exist
    :param data_dir: Directory to download the model to
    """
    vgg_filename = 'vgg.zip'
    vgg_path = os.path.join(data_dir, 'vgg')
    vgg_files = [
        os.path.join(vgg_path, 'variables/variables.data-00000-of-00001'),
        os.path.join(vgg_path, 'variables/variables.index'),
        os.path.join(vgg_path, 'saved_model.pb')]

    missing_vgg_files = [vgg_file for vgg_file in vgg_files if not os.path.exists(vgg_file)]
    if missing_vgg_files:
        # Clean vgg dir
        if os.path.exists(vgg_path):
            shutil.rmtree(vgg_path)
        os.makedirs(vgg_path)

        # Download vgg
        print('Downloading pre-trained vgg model...')
        with DLProgress(unit='B', unit_scale=True, miniters=1) as pbar:
            urlretrieve(
                'https://s3-us-west-1.amazonaws.com/udacity-selfdrivingcar/vgg.zip',
                os.path.join(vgg_path, vgg_filename),
                pbar.hook)

        # Extract vgg
        print('Extracting model...')
        zip_ref = zipfile.ZipFile(os.path.join(vgg_path, vgg_filename), 'r')
        zip_ref.extractall(data_dir)
        zip_ref.close()

        # Remove zip file to save space
        os.remove(os.path.join(vgg_path, vgg_filename))


def gen_batch_function(data_folder, image_shape):
    """
    Generate function to create batches of training data
    :param data_folder: Path to folder that contains all the datasets
    :param image_shape: Tuple - Shape of image
    :return:
    """
    def get_batches_fn(batch_size):
        """
        Create batches of training data
        :param batch_size: Batch Size
        :return: Batches of training data
        """
        image_paths = glob(os.path.join(data_folder, 'CameraRGB', '*.png'))
        label_paths = glob(os.path.join(data_folder, 'CameraPrep', '*.png'))

        paths = list(zip(image_paths, label_paths))[:LIMIT]
        random.shuffle(paths)
        for batch_i in range(0, len(paths), batch_size):
            images = []
            gt_images = []
            for image_file, gt_image_file in paths[batch_i:batch_i+batch_size]:
                image = cv2.imread(image_file)[:, :, ::-1]
                gt_image = cv2.imread(gt_image_file)[:, :, -1]
                temp = np.zeros_like(gt_image)
                temp[gt_image == 7] = 1
                temp[gt_image == 10] = 2
                gt_image = temp
                images.append(image)
                gt_images.append(gt_image)

            yield np.array(images), np.array(gt_images)
    return get_batches_fn


def gen_test_output(sess, logits, keep_prob, image_pl, data_folder, image_shape):
    """
    Generate test output using the test images
    :param sess: TF session
    :param logits: TF Tensor for the logits
    :param keep_prob: TF Placeholder for the dropout keep robability
    :param image_pl: TF Placeholder for the image placeholder
    :param data_folder: Path to the folder that contains the datasets
    :param image_shape: Tuple - Shape of image
    :return: Output for for each test image
    """
    for image_file in glob(os.path.join(data_folder, 'CameraRGB', '*.png'))[LIMIT:LIMIT + 2]:
        image = cv2.imread(image_file)[:, :, ::-1]

        im_softmax = sess.run(
            [tf.nn.softmax(logits)],
            {keep_prob: 1.0, image_pl: [image]})

        result = np.argmax(im_softmax, axis = -1)
        #road_softmax = im_softmax[0][:, 1].reshape(image_shape[0], image_shape[1])
        road_seg = (result == 1).reshape(image_shape[0], image_shape[1], 1)
        mask_road = np.dot(road_seg, np.array([[0, 255, 0, 127]]))
        mask_road = scipy.misc.toimage(mask_road, mode="RGBA")

        # veh_softmax = im_softmax[0][:, 2].reshape(image_shape[0], image_shape[1])
        veh_seg = (result == 2).reshape(image_shape[0], image_shape[1], 1)
        mask_veh = np.dot(veh_seg, np.array([[255, 0, 0, 127]]))
        mask_veh = scipy.misc.toimage(mask_veh, mode="RGBA")

        street_im = scipy.misc.toimage(image)
        street_im.paste(mask_veh, box=None, mask=mask_veh)
        street_im.paste(mask_road, box=None, mask=mask_road)

        raw_im = np.zeros_like(image)
        raw_im = raw_im + np.dot(veh_seg, [[255, 0, 0]]) + np.dot(road_seg, [[0, 255, 0]])


        yield os.path.basename(image_file), np.array(street_im), np.array(raw_im)


def save_inference_samples(runs_dir, data_dir, sess, image_shape, logits, keep_prob, input_image):
    # Make folder for current run
    output_dir = os.path.join(runs_dir, str(time.time()))
    if os.path.exists(output_dir):
        shutil.rmtree(output_dir)
    os.makedirs(output_dir)

    # Run NN on test images and save them to HD
    print('Training Finished. Saving test images to: {}'.format(output_dir))
    image_outputs = gen_test_output(
        sess, logits, keep_prob, input_image, data_dir, image_shape)
    for name, image, raw_image in image_outputs:
        scipy.misc.imsave(os.path.join(output_dir, name), image)
        scipy.misc.imsave(os.path.join(output_dir, "raw_" + name), raw_image)
