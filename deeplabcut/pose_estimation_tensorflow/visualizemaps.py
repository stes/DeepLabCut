"""
DeepLabCut2.0 Toolbox (deeplabcut.org)
© A. & M. Mathis Labs
https://github.com/AlexEMG/DeepLabCut

Please see AUTHORS for contributors.
https://github.com/AlexEMG/DeepLabCut/blob/master/AUTHORS
Licensed under GNU Lesser General Public License v3.0
"""

import os
import cv2
import matplotlib.pyplot as plt
import numpy as np


def extract_maps(config, shuffle=0, trainingsetindex=0, comparisonbodyparts="all",
                 gputouse=None, rescale=False, Indices=None, modelprefix=''):
    """
    Extracts the scoremap, locref, partaffinityfields (if available).

    Returns a dictionary indexed by: trainingsetfraction, snapshotindex, and imageindex
    for those keys, each item contains: (image,scmap,locref,paf,bpt names,partaffinity graph, imagename, True/False if this image was in trainingset)
    ----------
    config : string
        Full path of the config.yaml file as a string.

    shuffle: integer
        integers specifying shuffle index of the training dataset. The default is 0.

    trainingsetindex: int, optional
        Integer specifying which TrainingsetFraction to use. By default the first (note that TrainingFraction is a list in config.yaml). This
        variable can also be set to "all".

    comparisonbodyparts: list of bodyparts, Default is "all".
        The average error will be computed for those body parts only (Has to be a subset of the body parts).

    rescale: bool, default False
        Evaluate the model at the 'global_scale' variable (as set in the test/pose_config.yaml file for a particular project). I.e. every
        image will be resized according to that scale and prediction will be compared to the resized ground truth. The error will be reported
        in pixels at rescaled to the *original* size. I.e. For a [200,200] pixel image evaluated at global_scale=.5, the predictions are calculated
        on [100,100] pixel images, compared to 1/2*ground truth and this error is then multiplied by 2!. The evaluation images are also shown for the
        original size!

    Examples
    --------
    If you want to extract the data for image 0 and 103 (of the training set) for model trained with shuffle 0.
    >>> deeplabcut.extract_maps(configfile,0,Indices=[0,103])

    """
    from deeplabcut.utils.auxfun_videos import imread, imresize
    from deeplabcut.pose_estimation_tensorflow.nnet import predict
    from deeplabcut.pose_estimation_tensorflow.nnet import predict_multianimal as predictma
    from deeplabcut.pose_estimation_tensorflow.config import load_config
    from deeplabcut.pose_estimation_tensorflow.dataset.pose_dataset import data_to_input
    from deeplabcut.utils import auxiliaryfunctions
    from tqdm import tqdm
    import tensorflow as tf
    vers = (tf.__version__).split('.')
    if int(vers[0])==1 and int(vers[1])>12:
        TF=tf.compat.v1
    else:
        TF=tf

    import pandas as pd
    from pathlib import Path
    import numpy as np

    TF.reset_default_graph()
    os.environ['TF_CPP_MIN_LOG_LEVEL'] = '2' #
#    tf.logging.set_verbosity(tf.logging.WARN)

    start_path=os.getcwd()
    # Read file path for pose_config file. >> pass it on
    cfg = auxiliaryfunctions.read_config(config)

    if gputouse is not None: #gpu selectinon
            os.environ['CUDA_VISIBLE_DEVICES'] = str(gputouse)
    
    if trainingsetindex=='all':
        TrainingFractions=cfg["TrainingFraction"]
    else:
        if trainingsetindex<len(cfg["TrainingFraction"]) and trainingsetindex>=0:
            TrainingFractions=[cfg["TrainingFraction"][int(trainingsetindex)]]
        else:
            raise Exception('Please check the trainingsetindex! ', trainingsetindex, ' should be an integer from 0 .. ', int(len(cfg["TrainingFraction"])-1))

    # Loading human annotatated data
    trainingsetfolder=auxiliaryfunctions.GetTrainingSetFolder(cfg)
    Data=pd.read_hdf(os.path.join(cfg["project_path"],str(trainingsetfolder),'CollectedData_' + cfg["scorer"] + '.h5'),'df_with_missing')

    # Get list of body parts to evaluate network for
    comparisonbodyparts=auxiliaryfunctions.IntersectionofBodyPartsandOnesGivenbyUser(cfg,comparisonbodyparts)
    # Make folder for evaluation
    auxiliaryfunctions.attempttomakefolder(str(cfg["project_path"]+"/evaluation-results/"))

    Maps={}
    for trainFraction in TrainingFractions:
            Maps[trainFraction]={}
            ##################################################
            # Load and setup CNN part detector
            ##################################################
            datafn,metadatafn=auxiliaryfunctions.GetDataandMetaDataFilenames(trainingsetfolder,trainFraction,shuffle,cfg)

            modelfolder=os.path.join(cfg["project_path"],str(auxiliaryfunctions.GetModelFolder(trainFraction,shuffle,cfg,modelprefix=modelprefix)))
            path_test_config = Path(modelfolder) / 'test' / 'pose_cfg.yaml'
            # Load meta data
            data, trainIndices, testIndices, trainFraction=auxiliaryfunctions.LoadMetadata(os.path.join(cfg["project_path"],metadatafn))
            try:
                dlc_cfg = load_config(str(path_test_config))
            except FileNotFoundError:
                raise FileNotFoundError("It seems the model for shuffle %s and trainFraction %s does not exist."%(shuffle,trainFraction))

            #change batch size, if it was edited during analysis!
            dlc_cfg['batch_size']=1 #in case this was edited for analysis.

            #Create folder structure to store results.
            evaluationfolder=os.path.join(cfg["project_path"],str(auxiliaryfunctions.GetEvaluationFolder(trainFraction,shuffle,cfg,modelprefix=modelprefix)))
            auxiliaryfunctions.attempttomakefolder(evaluationfolder,recursive=True)
            #path_train_config = modelfolder / 'train' / 'pose_cfg.yaml'

            # Check which snapshots are available and sort them by # iterations
            Snapshots = np.array([fn.split('.')[0]for fn in os.listdir(os.path.join(str(modelfolder), 'train'))if "index" in fn])
            try: #check if any where found?
              Snapshots[0]
            except IndexError:
              raise FileNotFoundError("Snapshots not found! It seems the dataset for shuffle %s and trainFraction %s is not trained.\nPlease train it before evaluating.\nUse the function 'train_network' to do so."%(shuffle,trainFraction))

            increasing_indices = np.argsort([int(m.split('-')[1]) for m in Snapshots])
            Snapshots = Snapshots[increasing_indices]

            if cfg["snapshotindex"] == -1:
                snapindices = [-1]
            elif cfg["snapshotindex"] == "all":
                snapindices = range(len(Snapshots))
            elif cfg["snapshotindex"]<len(Snapshots):
                snapindices=[cfg["snapshotindex"]]
            else:
                print("Invalid choice, only -1 (last), any integer up to last, or all (as string)!")

            ########################### RESCALING (to global scale)
            if rescale==True:
                scale=dlc_cfg['global_scale']
                Data=pd.read_hdf(os.path.join(cfg["project_path"],str(trainingsetfolder),'CollectedData_' + cfg["scorer"] + '.h5'),'df_with_missing')*scale
            else:
                scale=1

            bptnames=[dlc_cfg['all_joints_names'][i] for i in range(len(dlc_cfg['all_joints']))]

            for snapindex in snapindices:
                dlc_cfg['init_weights'] = os.path.join(str(modelfolder),'train',Snapshots[snapindex]) #setting weights to corresponding snapshot.
                trainingsiterations = (dlc_cfg['init_weights'].split(os.sep)[-1]).split('-')[-1] #read how many training siterations that corresponds to.

                # Name for deeplabcut net (based on its parameters)
                #DLCscorer,DLCscorerlegacy = auxiliaryfunctions.GetScorerName(cfg,shuffle,trainFraction,trainingsiterations)
                #notanalyzed, resultsfilename, DLCscorer=auxiliaryfunctions.CheckifNotEvaluated(str(evaluationfolder),DLCscorer,DLCscorerlegacy,Snapshots[snapindex])
                #print("Extracting maps for ", DLCscorer, " with # of trainingiterations:", trainingsiterations)
                #if notanalyzed: #this only applies to ask if h5 exists...
                
                # Specifying state of model (snapshot / training state)
                sess, inputs, outputs = predict.setup_pose_prediction(dlc_cfg)
                Numimages = len(Data.index)
                PredicteData = np.zeros((Numimages,3 * len(dlc_cfg['all_joints_names'])))
                print("Analyzing data...")
                if Indices is None:
                    Indices=enumerate(Data.index)
                else:
                    Ind = [Data.index[j] for j in Indices]
                    Indices=enumerate(Ind)

                DATA={}
                for imageindex, imagename in tqdm(Indices):
                    image = imread(os.path.join(cfg['project_path'],imagename),mode='RGB')
                    if scale!=1:
                        image = imresize(image, scale)

                    image_batch = data_to_input(image)
                    # Compute prediction with the CNN
                    outputs_np = sess.run(outputs, feed_dict={inputs: image_batch})

                    if cfg.get('multianimalproject',False):
                        scmap, locref, paf= predictma.extract_cnn_output(outputs_np, dlc_cfg)
                        pagraph=dlc_cfg['partaffinityfield_graph']
                    else:
                        scmap, locref = predict.extract_cnn_output(outputs_np, dlc_cfg)
                        paf = None
                        pagraph=[]

                    if imageindex in testIndices:
                        trainingfram=False
                    else:
                        trainingfram=True
                    
                    DATA[imageindex]=[image, scmap,locref ,paf ,bptnames ,pagraph ,imagename ,trainingfram]
                #return DATA
                Maps[trainFraction][Snapshots[snapindex]]=DATA
    os.chdir(str(start_path))
    return Maps


def resize_to_same_shape(array, array_dest):
    shape_dest = array_dest.shape
    return cv2.resize(array, (shape_dest[1], shape_dest[0]), interpolation=cv2.INTER_CUBIC)


def resize_all_maps(image, scmap, locref, paf):
    #print(np.shape(image),np.shape(scmap),np.shape(locref),np.shape(paf))
    scmap = resize_to_same_shape(scmap, image)
    locref_x = resize_to_same_shape(locref[:, :, :, 0], image)
    locref_y = resize_to_same_shape(locref[:, :, :, 1], image)
    if paf is not None:
        paf = resize_to_same_shape(paf, image)
    return scmap, (locref_x, locref_y), paf


def form_grid_layout(nplots, nplots_per_row, nx, ny, labels):
    nrows =int(np.ceil(nplots / nplots_per_row))
    fig, axes = plt.subplots(nrows, nplots_per_row, frameon=False)
    for i, ax in enumerate(axes.flat):
        if i < nplots:
            if labels is not None:
                ax.set_title(labels[i])
            ax.set_xlim(0, nx)
            ax.set_ylim(0, ny)
            ax.axis('off')
            ax.invert_yaxis()
        else:
            ax.axis('off')
    fig.tight_layout()
    return fig, axes


def visualize_scoremaps(image, scmap, nplots_per_row=3, labels=None):
    ny, nx = np.shape(image)[:2]
    nplots = scmap.shape[2]
    fig, axes = form_grid_layout(nplots, nplots_per_row, nx, ny, labels=labels)
    for i, ax in enumerate(axes.flat):
        if i < nplots:
            ax.imshow(image)
            ax.imshow(scmap[:, :, i], alpha=0.5)
    return fig, axes


def visualize_locrefs(image, scmap, locref_x, locref_y, step=5, zoom_width=0, nplots_per_row=3, labels=None):
    fig, axes = visualize_scoremaps(image, scmap, nplots_per_row, labels)
    nplots = scmap.shape[2]
    for i, ax in enumerate(axes.flat):
        if i < nplots:
            U = locref_x[:, :, i]
            V = locref_y[:, :, i]
            X, Y = np.meshgrid(np.arange(U.shape[1]), np.arange(U.shape[0]))
            M = np.zeros(U.shape, dtype='bool')
            map_ = scmap[:, :, i]
            M[map_ < .5] = True
            U = np.ma.masked_array(U, mask=M)
            V = np.ma.masked_array(V, mask=M)
            ax.quiver(X[::step, ::step], Y[::step, ::step], U[::step, ::step], V[::step, ::step],
                      color='r', units='x', scale_units='xy', scale=1, angles='xy')
            if zoom_width > 0:
                maxloc = np.unravel_index(np.argmax(map_), map_.shape)
                ax.set_xlim(maxloc[1] - zoom_width, maxloc[1] + zoom_width)
                ax.set_ylim(maxloc[0] + zoom_width, maxloc[0] - zoom_width)
    return fig, axes


def visualize_paf(image, paf, pafgraph, nplots_per_row=3, step=5, labels=None):
    ny, nx = np.shape(image)[:2]
    nplots = len(pafgraph)
    titles = [(labels[i], labels[j]) for i, j in pafgraph] if labels is not None else labels
    fig, axes = form_grid_layout(nplots, nplots_per_row, nx, ny, labels=titles)
    for i, ax in enumerate(axes.flat):
        if i < nplots:
            ax.imshow(image)
            U = paf[:, :, 2 * i]
            V = paf[:, :, 2 * i + 1]
            X, Y = np.meshgrid(np.arange(U.shape[1]), np.arange(U.shape[0]))
            M = np.zeros(U.shape, dtype='bool')
            M[U ** 2 + V ** 2 < 0.5 * 0.5 ** 2] = True
            U = np.ma.masked_array(U, mask=M)
            V = np.ma.masked_array(V, mask=M)
            ax.quiver(X[::step, ::step], Y[::step, ::step], U[::step, ::step], V[::step, ::step],
                    scale=50, headaxislength=4, alpha=1, width=0.002, color='r', angles='xy')
    return fig, axes


def extract_save_all_maps(config, shuffle=1, trainingsetindex=0, comparisonbodyparts='all',
                  gputouse=None, rescale=False, Indices=None, modelprefix='', dest_folder=None, nplots_per_row=None):
    """
    Extracts the scoremap, location refinement field and part affinity field prediction of the model. The maps 
    will be rescaled to the size of the input image and stored in the corresponding model folder in /evaluation-results.

    ----------
    config : string
        Full path of the config.yaml file as a string.

    shuffle: integer
        integers specifying shuffle index of the training dataset. The default is 1.

    trainingsetindex: int, optional
        Integer specifying which TrainingsetFraction to use. By default the first (note that TrainingFraction is a list in config.yaml). This
        variable can also be set to "all".

    comparisonbodyparts: list of bodyparts, Default is "all".
        The average error will be computed for those body parts only (Has to be a subset of the body parts).

    Indices: default None
        For which images shall the scmap/locref and paf be computed? Give a list of images

    nplots_per_row: int, optional (default=None)
        Number of plots per row in grid plots. By default, calculated to approximate a squared grid of plots
        
    Examples
    --------
    Calculated maps for images 0, 1 and 33.
    >>> deeplabcut.extract_save_all_maps('/analysis/project/reaching-task/config.yaml', shuffle=1,Indices=[0,1,33])

    """

    from deeplabcut.utils.auxiliaryfunctions import read_config, attempttomakefolder, GetEvaluationFolder
    from tqdm import tqdm

    cfg = read_config(config)
    data = extract_maps(config, shuffle, trainingsetindex, comparisonbodyparts,
                        gputouse, rescale, Indices, modelprefix)

    if not nplots_per_row:
        from deeplabcut.utils import auxiliaryfunctions
        bpts = auxiliaryfunctions.IntersectionofBodyPartsandOnesGivenbyUser(cfg, comparisonbodyparts)
        nplots_per_row = np.floor(np.sqrt(len(bpts)))

    print("Saving plots...")
    for frac, values in data.items():
        if not dest_folder:
            #dest_folder = os.path.join(cfg['project_path'], 'maps')
            dest_folder = os.path.join(cfg["project_path"],str(GetEvaluationFolder(frac,shuffle,cfg,modelprefix=modelprefix)), 'maps')
        attempttomakefolder(dest_folder)
        dest_path = os.path.join(dest_folder, '{}_{}_{}_{}_{}_{}.png')

        for snap, maps in values.items():
            for imagenr in tqdm(maps):
                image, scmap, locref, paf, bptnames, pafgraph, impath, trainingframe = maps[imagenr]
                label = 'train' if trainingframe else 'test'
                imname = os.path.split(os.path.splitext(impath)[0])[1]
                if not os.path.isfile(dest_path.format(imagenr, 'scmap', label, shuffle, frac, snap)):
                    scmap, (locref_x, locref_y), paf = resize_all_maps(image, scmap, locref, paf)
                    fig1, _ = visualize_scoremaps(image, scmap, labels=bptnames, nplots_per_row=nplots_per_row)
                    fig2, _ = visualize_locrefs(image, scmap, locref_x, locref_y, labels=bptnames, nplots_per_row=nplots_per_row)
                    fig3, _ = visualize_locrefs(image, scmap, locref_x, locref_y, zoom_width=100, labels=bptnames, nplots_per_row=nplots_per_row)
                    if paf is not None:
                        fig4, _ = visualize_paf(image, paf, pafgraph, labels=bptnames, nplots_per_row=nplots_per_row)

                    fig1.savefig(dest_path.format(imname, 'scmap', label, shuffle, frac, snap))
                    fig2.savefig(dest_path.format(imname, 'locref', label, shuffle, frac, snap))
                    fig3.savefig(dest_path.format(imname, 'locrefzoom', label, shuffle, frac, snap))
                    if paf is not None:
                        fig4.savefig(dest_path.format(imname, 'paf', label, shuffle, frac, snap))
                    
                    plt.close('all')