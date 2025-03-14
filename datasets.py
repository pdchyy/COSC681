

import tensorflow as tf
import os
import pandas as pd
import cv2
import numpy as np
import math
from pathlib import Path
import matplotlib.pyplot as pyplot


class TrackNetDataset(tf.keras.utils.Sequence):

    def __init__(self, input_height=360, input_width=640, batch_size=2):
        self.path_dataset = Path(__file__).parent
        self.data = pd.read_csv(os.path.join(self.path_dataset, 'labels_train.csv'))
        print(f'#training samples : {self.data.shape[0]}')
        self.height = input_height
        self.width = input_width
        self.batch_size = batch_size


    def __len__(self):
        # Number of batches
        return (self.data.shape[0] + self.batch_size - 1) // self.batch_size


    def __getitem__(self, batch_idx):
        start_idx = batch_idx * self.batch_size
        end_idx = (batch_idx + 1) * self.batch_size
        batch_data = self.data.iloc[start_idx:end_idx]

        inputs_batch = []
        outputs_batch = []

        for idx in range(len(batch_data)):
            path, path_prev, path_preprev, path_gt, x, y, status, vis = batch_data.iloc[idx]

            path = os.path.join(self.path_dataset, path)
            path_prev = os.path.join(self.path_dataset, path_prev)
            path_preprev = os.path.join(self.path_dataset, path_preprev)
            path_gt = os.path.join(self.path_dataset, path_gt)
            if math.isnan(x):
                x = -1
                y = -1
                
            inputs = self.get_input(path, path_prev, path_preprev)
            outputs = self.get_output(path_gt) #TrackNet +SCCE loss
            # outputs = self.generate_binary_heatmap(x, y, 5, 1) # for TrackNet2 + WBCE_loss, ball radius: 5 pixels
            # outputs = np.reshape(outputs, (self.width *self.height))
            inputs_batch.append(inputs)
            outputs_batch.append(outputs)
            
        return np.array(inputs_batch), np.array(outputs_batch)


    def get_input(self, path, path_prev, path_preprev):

        img = cv2.imread(path)
        img = cv2.resize(img, (self.width, self.height))

        img_prev = cv2.imread(path_prev)
        img_prev = cv2.resize(img_prev, (self.width, self.height))

        img_preprev = cv2.imread(path_preprev)
        img_preprev = cv2.resize(img_preprev, (self.width, self.height))

        imgs = np.concatenate((img, img_prev, img_preprev), axis=2)
        imgs = imgs.astype(np.float32) / 255.0

        imgs = np.rollaxis(imgs, 2, 0) # The axis 2 is moved to the front
       
        return np.array(imgs)


    def get_output(self, path_gt):
        """ This is the y_true heatmap.
        """
        img = cv2.imread(path_gt) # img.shape = (720,1280,3)
        img = cv2.resize(img, (self.width, self.height)) # Reduce (720, 1280) to (640, 360)
        img = img[:, :, 0] # Only the first is the ground_true frame because 3 channels are taken
        # For WBCE_loss + Binary heatMap to fit the output of the model ####################
        img = img/255
        img = img > 0.5
        img = img.astype('float32')
        #######################################################################################
        img = np.reshape(img, (self.width * self.height)) # For SparceCategoricalCrossEntropy loss finction and WBCE_loss
        
        return img


    def generate_binary_heatmap(self, cx, cy, r, mag):
        if cx < 0 or cy < 0:
            return np.zeros((1, self.height, self.width))
        
        x, y = np.meshgrid(np.linspace(1, self.width, self.width), np.linspace(1, self.height, self.height))
        heatmap = ((y - (cy + 1))**2) + ((x - (cx + 1))**2) # ?
        heatmap[heatmap <= r**2] = 1
        heatmap[heatmap > r**2] = 0
        y = heatmap*mag
        y = np.reshape(y, (1, self.height, self.width))

        return y
    

    
