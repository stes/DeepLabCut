"""
DeepLabCut2.0 Toolbox (deeplabcut.org)
© A. & M. Mathis Labs
https://github.com/AlexEMG/DeepLabCut

Please see AUTHORS for contributors.
https://github.com/AlexEMG/DeepLabCut/blob/master/AUTHORS
Licensed under GNU Lesser General Public License v3.0
"""

####################################################
# Dependencies
####################################################
import os.path
from pathlib import Path
import argparse
from deeplabcut.utils import auxiliaryfunctions, auxfun_multianimal
import numpy as np
import matplotlib.pyplot as plt
import os

# https://stackoverflow.com/questions/14720331/how-to-generate-random-colors-in-matplotlib
def get_cmap(n, name='hsv'):
    '''Returns a function that maps each index in 0, 1, ..., n-1 to a distinct
    RGB color; the keyword argument name must be a standard mpl colormap name.'''
    return plt.cm.get_cmap(name, n)

def Histogram(vector,color,bins, ax=None):
    dvector=np.diff(vector)
    dvector=dvector[np.isfinite(dvector)]
    if ax is None:
        fig = plt.figure()
        ax = fig.add_subplot(111)
    ax.hist(dvector,color=color,histtype='step',bins=bins)

def PlottingResults(tmpfolder, Dataframe, cfg, bodyparts2plot, individuals2plot, showfigures=False, suffix='.png'):
    ''' Plots poses vs time; pose x vs pose y; histogram of differences and likelihoods.'''
    pcutoff = cfg['pcutoff']
    colors = get_cmap(len(bodyparts2plot), name=cfg['colormap'])
    alphavalue = cfg['alphavalue']
    if individuals2plot:
        Dataframe = Dataframe.copy().loc(axis=1)[:, individuals2plot]

    # Pose X vs pose Y
    fig1 = plt.figure(figsize=(8, 6))
    ax1 = fig1.add_subplot(111)
    ax1.set_xlabel('X position in pixels')
    ax1.set_ylabel('Y position in pixels')
    ax1.invert_yaxis()

    # Poses vs time
    fig2 = plt.figure(figsize=(30, 10))
    ax2 = fig2.add_subplot(111)
    ax2.set_xlabel('Frame Index')
    ax2.set_ylabel('X-(dashed) and Y- (solid) position in pixels')

    # Likelihoods
    fig3 = plt.figure(figsize=(30, 10))
    ax3 = fig3.add_subplot(111)
    ax3.set_xlabel('Frame Index')
    ax3.set_ylabel('Likelihood')

    # Histograms
    fig4 = plt.figure()
    ax4 = fig4.add_subplot(111)
    ax4.set_ylabel('Count')
    ax4.set_xlabel('DeltaX and DeltaY')
    bins = np.linspace(0, np.amax(Dataframe.max()), 100)

    for bpindex, bp in enumerate(bodyparts2plot):
        prob = Dataframe.xs((bp, 'likelihood'), level=(-2, -1), axis=1).values.squeeze()
        mask = prob < pcutoff
        temp_x = np.ma.array(Dataframe.xs((bp, 'x'), level=(-2, -1), axis=1).values.squeeze(), mask=mask)
        temp_y = np.ma.array(Dataframe.xs((bp, 'y'), level=(-2, -1), axis=1).values.squeeze(), mask=mask)
        ax1.plot(temp_x, temp_y, '.', color=colors(bpindex), alpha=alphavalue)

        ax2.plot(temp_x, '--', color=colors(bpindex), alpha=alphavalue)
        ax2.plot(temp_y, '-', color=colors(bpindex), alpha=alphavalue)

        ax3.plot(prob, '-', color=colors(bpindex), alpha=alphavalue)

        Histogram(temp_x, colors(bpindex), bins, ax4)
        Histogram(temp_y, colors(bpindex), bins, ax4)

    sm = plt.cm.ScalarMappable(cmap=plt.get_cmap(cfg['colormap']), norm=plt.Normalize(vmin=0, vmax=len(bodyparts2plot)-1))
    sm._A = []
    for ax in ax1, ax2, ax3, ax4:
        cbar = plt.colorbar(sm, ax=ax, ticks=range(len(bodyparts2plot)))
        cbar.set_ticklabels(bodyparts2plot)

    fig1.savefig(os.path.join(tmpfolder, 'trajectory' + suffix))
    fig2.savefig(os.path.join(tmpfolder, 'plot' + suffix))
    fig3.savefig(os.path.join(tmpfolder, 'plot-likelihood' + suffix))
    fig4.savefig(os.path.join(tmpfolder, 'hist' + suffix))

    if not showfigures:
        plt.close('all')
    else:
        plt.show()


##################################################
# Looping analysis over video
##################################################

def plot_trajectories(config, videos, videotype='.avi', shuffle=1, trainingsetindex=0, filtered=False,
                      displayedbodyparts='all', displayedindividuals='all', showfigures=False, destfolder=None,modelprefix=''):
    """
    Plots the trajectories of various bodyparts across the video.

    Parameters
    ----------
     config : string
    Full path of the config.yaml file as a string.

    videos : list
        A list of strings containing the full paths to videos for analysis or a path to the directory, where all the videos with same extension are stored.

    videotype: string, optional
        Checks for the extension of the video in case the input to the video is a directory.\n Only videos with this extension are analyzed. The default is ``.avi``

    shuffle: list, optional
    List of integers specifying the shuffle indices of the training dataset. The default is [1]

    trainingsetindex: int, optional
    Integer specifying which TrainingsetFraction to use. By default the first (note that TrainingFraction is a list in config.yaml).

    filtered: bool, default false
    Boolean variable indicating if filtered output should be plotted rather than frame-by-frame predictions. Filtered version can be calculated with deeplabcut.filterpredictions

    displayedbodyparts: list of strings, optional
        This select the body parts that are plotted in the video.
        Either ``all``, then all body parts from config.yaml are used,
        or a list of strings that are a subset of the full list.
        E.g. ['hand','Joystick'] for the demo Reaching-Mackenzie-2018-08-30/config.yaml to select only these two body parts.

    showfigures: bool, default false
    If true then plots are also displayed.

    destfolder: string, optional
        Specifies the destination folder that was used for storing analysis data (default is the path of the video).

    Example
    --------
    for labeling the frames
    >>> deeplabcut.plot_trajectories('home/alex/analysis/project/reaching-task/config.yaml',['/home/alex/analysis/project/videos/reachingvideo1.avi'])
    --------

    """
    cfg = auxiliaryfunctions.read_config(config)
    trainFraction = cfg['TrainingFraction'][trainingsetindex]
    DLCscorer,DLCscorerlegacy = auxiliaryfunctions.GetScorerName(cfg,shuffle,trainFraction, modelprefix=modelprefix) #automatically loads corresponding model (even training iteration based on snapshot index)
    bodyparts = auxiliaryfunctions.IntersectionofBodyPartsandOnesGivenbyUser(cfg, displayedbodyparts)
    individuals = auxfun_multianimal.IntersectionofIndividualsandOnesGivenbyUser(cfg, displayedindividuals)
    Videos=auxiliaryfunctions.Getlistofvideos(videos,videotype)
    for video in Videos:
        print(video)
        if destfolder is None:
            videofolder = str(Path(video).parents[0])
        else:
            videofolder=destfolder

        vname = str(Path(video).stem)
        print("Starting % ", videofolder, video)
        notanalyzed, dataname, DLCscorer=auxiliaryfunctions.CheckifNotAnalyzed(videofolder,vname,DLCscorer,DLCscorerlegacy,flag='checking')

        if notanalyzed:
            print("The video was not analyzed with this scorer:", DLCscorer)
        else:
            #LoadData
            print("Loading ", video, "and data.")
            datafound,metadata,Dataframe,DLCscorer,suffix=auxiliaryfunctions.LoadAnalyzedData(str(videofolder),vname,DLCscorer,filtered) #returns boolean variable if data was found and metadata + pandas array
            if datafound:
                basefolder=videofolder
                auxiliaryfunctions.attempttomakefolder(basefolder)
                auxiliaryfunctions.attempttomakefolder(os.path.join(basefolder,'plot-poses'))
                tmpfolder = os.path.join(basefolder,'plot-poses', vname)
                auxiliaryfunctions.attempttomakefolder(tmpfolder)
                for individual in individuals:
                    PlottingResults(tmpfolder, Dataframe, cfg, bodyparts, individual,
                                    showfigures, suffix + individual + '.png')

    print('Plots created! Please check the directory "plot-poses" within the video directory')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('config')
    parser.add_argument('video')
    cli_args = parser.parse_args()
