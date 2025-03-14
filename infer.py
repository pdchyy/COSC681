from utils import heatMap
from tqdm import tqdm
import numpy as np
import argparse,cv2,os
from itertools import groupby
from scipy.spatial import distance
from keras.models import load_model
from pathlib import Path
import time

def read_video(path_video):
    """ Read video file    
    :params
        path_video: path to video file
    :return
        frames: list of video frames
        fps: frames per second
    """
    cap = cv2.VideoCapture(path_video)
    fps = int(cap.get(cv2.CAP_PROP_FPS))

    frames = []
    while cap.isOpened():
        ret, frame = cap.read()
        if ret:
            frames.append(frame)
        else:
            break
    cap.release()
    return frames, fps

def infer_model(frames, model):
    """ Run pretrained model on a consecutive list of frames    
    :params
        frames: list of consecutive video frames
        model: pretrained model
    :return    
        ball_track: list of detected ball points
        dists: list of euclidean distances between two neighbouring ball points
    """
    height = 360
    width = 640
    n_classes = 256
    # ratio = frames[2].shape[0] / height
    dists = [-1]*2
    ball_track = [(None,None)]*2
    output_height = frames[2].shape[0]
    output_width = frames[2].shape[1]
    for num in tqdm(range(2, len(frames))):
        img = cv2.resize(frames[num], (width, height))
        img_prev = cv2.resize(frames[num-1], (width, height))
        img_preprev = cv2.resize(frames[num-2], (width, height))
        imgs = np.concatenate((img, img_prev, img_preprev), axis=2) # combine 3 frames
        imgs = imgs.astype(np.float32)/255.0
        imgs = np.rollaxis(imgs, 2, 0) # Since the order of TrackNet is "channel_first", the axis need to change.
        prediction = model.predict(np.array([imgs]),verbose=0)[0]
        
        x_pred,y_pred=heatMap(prediction, n_classes, height, width, output_height, output_width)
        ball_track.append((x_pred, y_pred))

        if ball_track[-1][0] and ball_track[-2][0]:
            dist = distance.euclidean(ball_track[-1], ball_track[-2])
        else:  # If the ball is none, not tracked, set the dist=-1.
            dist = -1
        dists.append(dist)  
    return ball_track, dists 

def infer_model_1(frames, model): # TrackNet2(U-Net+Sigmoid) + WBCE-loss
    """ Run pretrained model on a consecutive list of frames    
    :params
        frames: list of consecutive video frames
        model: pretrained model
    :return    
        ball_track: list of detected ball points
        dists: list of euclidean distances between two neighbouring ball points
    """
    start_time = time.time()
    height = 360
    width = 640
    n_classes = 256
    # ratio = frames[2].shape[0] / height
    dists = [-1]*2
    ball_track = [(None,None)]*2
    output_height = frames[0].shape[0]
    output_width = frames[0].shape[1]
    for num in range(2, len(frames)):
        img = cv2.resize(frames[num], (width, height))
        img_prev = cv2.resize(frames[num-1], (width, height))
        img_preprev = cv2.resize(frames[num-2], (width, height))
        imgs = np.concatenate((img, img_prev, img_preprev), axis=2) # combine 3 frames
        imgs = imgs.astype(np.float32)/255.0
        imgs = np.rollaxis(imgs, 2, 0) # Since the order of TrackNet is "channel_first", the axis need to change.
        prediction = model.predict(np.array([imgs]),verbose=0)[0]
        
        x_pred,y_pred = heatMap_1(prediction, height, width, output_height, output_width)
        # x_pred,y_pred = binary_heatMap(prediction, height, width, output_height, output_width, ratio=2) # Not suitable for tennis ball tracking
        ball_track.append((x_pred, y_pred))

        if ball_track[-1][0] and ball_track[-2][0]:
            dist = distance.euclidean(ball_track[-1], ball_track[-2])
        else:
            dist = -1
        dists.append(dist)  
    run_time = time.time() - start_time
    print( "The infer_model_1 running time is ", run_time)
    return ball_track, dists 

def remove_outliers(ball_track, dists, max_dist = 100):
    """ Remove outliers from model prediction    
    :params
        ball_track: list of detected ball points
        dists: list of euclidean distances between two neighbouring ball points
        max_dist: maximum distance between two neighbouring ball points
    :return
        ball_track: list of ball points
    """
    outliers = list(np.where(np.array(dists) > max_dist)[0])
    for i in outliers:
        if i+1>=len(dists):
            break
        if (dists[i+1] > max_dist) | (dists[i+1] == -1):       
            ball_track[i] = (None, None)
            outliers.remove(i)
        elif dists[i-1] == -1:
            ball_track[i-1] = (None, None)
    return ball_track  

def split_track(ball_track, max_gap=4, max_dist_gap=80, min_track=5):
    """ Split ball track into several subtracks in each of which we will perform
    ball interpolation.    
    :params
        ball_track: list of detected ball points
        max_gap: maximun number of coherent None values for interpolation  
        max_dist_gap: maximum distance at which neighboring points remain in one subtrack
        min_track: minimum number of frames in each subtrack    
    :return
        result: list of subtrack indexes    
    """
    list_det = [0 if x[0] else 1 for x in ball_track]
    groups = [(k, sum(1 for _ in g)) for k, g in groupby(list_det)]

    cursor = 0
    min_value = 0
    result = []
    for i, (k, l) in enumerate(groups):
        if (k == 1) & (i > 0) & (i < len(groups) - 1):
            dist = distance.euclidean(ball_track[cursor-1], ball_track[cursor+l])
            if (l >=max_gap) | (dist/l > max_dist_gap):
                if cursor - min_value > min_track:
                    result.append([min_value, cursor])
                    min_value = cursor + l - 1        
        cursor += l
    if len(list_det) - min_value > min_track: 
        result.append([min_value, len(list_det)]) 
    return result    

def interpolation(coords):
    """ Run ball interpolation in one subtrack    
    :params
        coords: list of ball coordinates of one subtrack    
    :return
        track: list of interpolated ball coordinates of one subtrack
    """
    def nan_helper(y):
        return np.isnan(y), lambda z: z.nonzero()[0]

    x = np.array([x[0] if x[0] is not None else np.nan for x in coords])
    y = np.array([x[1] if x[1] is not None else np.nan for x in coords])

    nons, yy = nan_helper(x)
    x[nons]= np.interp(yy(nons), yy(~nons), x[~nons])
    nans, xx = nan_helper(y)
    y[nans]= np.interp(xx(nans), xx(~nans), y[~nans])

    track = [*zip(x,y)]
    return track

def write_track(frames, ball_track, path_output_video, fps, trace=7):
    """ Write .avi file with detected ball tracks
    :params
        frames: list of original video frames
        ball_track: list of ball coordinates
        path_output_video: path to output video
        fps: frames per second
        trace: number of frames with detected trace
    """
    height, width = frames[0].shape[:2]
    # out = cv2.VideoWriter(path_output_video, cv2.VideoWriter_fourcc(*'DIVX'), 
    out = cv2.VideoWriter(path_output_video, cv2.VideoWriter_fourcc(*'mp4v'),                      
                          fps, (width, height))
    for num in range(len(frames)):
        frame = frames[num]
        for i in range(trace):
            if (num-i > 0):
                if ball_track[num-i][0]:
                    x = int(ball_track[num-i][0])
                    y = int(ball_track[num-i][1])
                    frame = cv2.circle(frame, (x,y), radius=0, color = (0, 225, 165) , thickness=10-i)
                else:
                    break
        out.write(frame) 
    print("lllllllllllllllllllllllllllll")
    out.release()    

if __name__ == '__main__':
    root = Path(__file__).parent
    parser = argparse.ArgumentParser()
    parser.add_argument('--batch_size', type=int, default=2, help='batch size')
    parser.add_argument('--saved_model_path', type=str, default = os.path.join(root, 'models/tracknet.keras'), help='path to model')
    parser.add_argument('--input_video_path', type=str, help='path to input video')
    parser.add_argument('--output_video_path', type=str, help='path to output video')
    parser.add_argument('--extrapolation', default = False, action='store_true', help='whether to use ball track extrapolation')
    args = parser.parse_args()
    
    model = load_model(args.saved_model_path)
    frames, fps = read_video(args.input_video_path)
    ball_track, dists = infer_model(frames, model)
    ball_track = remove_outliers(ball_track, dists)    
    
    if args.extrapolation:
        subtracks = split_track(ball_track)
        for r in subtracks:
            ball_subtrack = ball_track[r[0]:r[1]]
            ball_subtrack = interpolation(ball_subtrack)
            ball_track[r[0]:r[1]] = ball_subtrack
        
    write_track(frames, ball_track, args.output_video_path, fps)    
    
    
    
    
    
