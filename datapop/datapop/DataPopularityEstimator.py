from __future__ import division, print_function, absolute_import

__author__ = 'mikhail91'

######################
###Version 0.2     ###
######################
###Using REP v0.5  ###
######################

import numpy as np
import pandas as pd
import re

try:
    import rep
except ImportError as e:
    raise ImportError("Install REP.")

from rep.utils import train_test_split
from rep.utils import Flattener
from sklearn.metrics import roc_auc_score
from sklearn.metrics import roc_curve, auc
from rep.metaml import FoldingClassifier #new
import matplotlib.pyplot as plt
from rep.classifiers import SklearnClassifier #scikit-learn branch
from sklearn.ensemble import GradientBoostingClassifier #scikit-learn branch
from .DataBase import DataBase


class DataPopularityEstimator(DataBase):
    """
    Data sets popularity estimator.
    XGBoost tree booster is used.
    Parameters:
    -----------
    :param str source_path: a train data file path.
    The data file must have .xls, .xlsx or .csv formats.

    :param pandas.DataFrame data: train data.

    :param int nb_of_weeks: number of weeks in data sets access history.
    """

    def __init__(self, source_path=None, data=None, nb_of_weeks=104):
        super(DataPopularityEstimator, self).__init__(source_path=source_path, data=data, nb_of_weeks=nb_of_weeks)

        self.train_report = None
        self.popularity = None


    def _features_intervals(self, data, periods):
        """
        Calculate new features
        :param pandas.DataFrame data: train data.
        :param list[str] periods: periods of data sets history access that are used to calculate new features
        :return: numpy.array new features
        """
        data_bv = data.copy()
        for i in range(0, len(periods)):
            if i!=0:
                data_bv[periods[i]] = data[periods[i]] - data[periods[i-1]]
        data_bv[periods] = (data_bv[periods] != 0)*1

        inter_max = []
        last_zeros = []
        nb_peaks = []
        inter_mean = []
        inter_std = []
        inter_rel = []

        for i in range(0,data_bv.shape[0]):
            ds = data_bv[periods].irow(i)
            nz = ds.nonzero()[0]
            inter = []

            nb_peaks.append(len(nz))
            if len(nz)==0:
                nz = [0]
            if len(nz)<2:
                inter = [0]
                #nz = [0]
            else:
                for k in range(0, len(nz)-1):
                    val = nz[k+1]-nz[k]
                    inter.append(val)

            inter = np.array(inter)
            inter_mean.append(inter.mean())
            inter_std.append(inter.std())
            if inter.mean()!=0:
                inter_rel.append(inter.std()/inter.mean())
            else:
                inter_rel.append(0)

            last_zeros.append(int(periods[-1]) - nz[-1] + 1)
            inter_max.append(max(inter))

        return np.array(inter_max), np.array(last_zeros), np.array(nb_peaks), np.array(inter_mean), np.array(inter_std), np.array(inter_rel)

    def _features_mass_center(self, data, periods):
        """
        Calculate new features
        :param pandas.DataFrame data: train data.
        :param list[str] periods: periods of data sets history access that are used to calculate new features
        :return: numpy.array new features
        """
        data_bv = data.copy()
        p = np.array(map(int, periods)) - int(periods[0])+1
        for i in range(0, len(periods)):
            if i!=0:
                data_bv[periods[i]] = data[periods[i]] - data[periods[i-1]]
        max_values = data_bv[periods].max(axis=1)
        for i in range(1, len(periods)):
            data_bv[periods[i]] = (data_bv[periods[i]]/(max_values+1)).values

        mass_center = []
        mass_center2 = []
        mass_moment = []
        r_moment = []

        for i in range(0,data_bv.shape[0]):
            center = (data_bv[periods].irow(i).values*p).sum()/(data_bv[periods].irow(i).values.sum()+1)
            center2 = (data_bv[periods].irow(i).values*np.square(p)).sum()
            moment = (data_bv[periods].irow(i).values*np.square(p-center)).sum()
            r_m = moment/(data_bv[periods].irow(i).values.sum()+1)
            mass_center.append(center)
            mass_center2.append(center2)
            mass_moment.append(moment)
            r_moment.append(r_m)

        return np.array(mass_center), np.array(mass_moment), np.array(r_moment), np.array(mass_center2)

    def _data_preparation(self):
        """
        Preparing data to train classifier
        :return:pandes.DataFrame for classifier, list[str] of features names
        """
        self._check_columns()
        periods = self.periods[:-26]
        df = pd.DataFrame()
        df['Name'] = self.data['Name']
        inter_max, last_zeros, nb_peaks, inter_mean, inter_std, inter_rel = self._features_intervals(self.data, periods)
        df['last_zeros'] = last_zeros
        df['inter_max'] = inter_max
        df['nb_peaks'] = nb_peaks
        df['inter_mean'] = inter_mean
        df['inter_std'] = inter_std
        df['inter_rel'] = inter_rel

        mass_center, mass_moment, r_moment, mass_center2 = self._features_mass_center(self.data, periods)
        df['mass_center'] = mass_center
        df['mass_center_sqr'] = mass_center2
        df['mass_moment'] = mass_moment
        df['r_moment'] = r_moment

        df['DiskSize'] = self.data['DiskSize'].values
        df['LFNSize'] = self.data['LFNSize'].values
        df['Nb_Replicas'] = self.data['Nb_Replicas'].values

        df['LogDiskSize'] = np.log(self.data['DiskSize'].values+0.00001)
        df['total_usage'] = self.data[periods[-1]].values
        df['mean_usage'] = df['total_usage'].values/(df['nb_peaks'].values+1)

        df['log_total_usage'] = np.log(self.data[periods[-1]].values+1)
        df['log_mean_usage'] = df['total_usage'].values - np.log(df['nb_peaks'].values+1)

        cols_str = ['Configuration', 'ProcessingPass', 'FileType', 'Storage']
        df_str = self.data.get(cols_str)
        for col in cols_str:
            unique = np.unique(df_str[col])
            index = range(0, len(unique))
            mapping = dict(zip(unique, index))
            df_str = df_str.replace({col:mapping})
        df['FileType'] = df_str['FileType'].values
        df['Configuration'] = df_str['Configuration'].values
        df['ProcessingPass'] = df_str['ProcessingPass'].values

        other_vars = [u'Type', u'Creation_week', u'NbLFN', u'LFNSize', u'NbDisk', u'DiskSize', u'NbTape', u'TapeSize',
                      u'NbArchived', u'ArchivedSize', u'Nb_Replicas', u'Nb_ArchReps', u'FirstUsage']
        for i in other_vars:
            df[i] = self.data[i].values

        df['silence'] = df['FirstUsage']-df[u'Creation_week']

        features = [u'last_zeros', u'inter_max', u'nb_peaks', u'inter_mean', u'inter_std', u'inter_rel', u'mass_center',
             u'mass_center_sqr', u'mass_moment', u'r_moment', u'DiskSize', u'LogDiskSize', u'total_usage', u'mean_usage',
             u'FileType', u'Configuration', u'ProcessingPass', u'log_total_usage', u'log_mean_usage']+other_vars
        return df, features

    def train(self):
        """
        Train classifier
        :return:1 if classifier trained successfully.
        """
        self._check_columns()
        df, features = self._data_preparation()
        labels = ((self.data[self.periods[-1]] - self.data[self.periods[-27]]) == 0).values*1

        try:
            n_folds = 10
            folder = FoldingClassifier(GradientBoostingClassifier(), n_folds=n_folds, features=features, random_state=42)
            folder.fit(df, labels)

        except:
            print ("Can not train classifier. Please, check data.")

        self.train_report = pd.DataFrame()
        self.train_report['Name'] = df['Name'].values
        self.train_report['Probability'] = folder.predict_proba(df)[:,1]
        self.train_report['Label'] = labels
        return 1

    def get_popularity(self):
        """
        Calculate data sets popularity
        :return:pandas.DataFrame with data sets popularity
        """

        assert self.train_report is not None, "Use 'train()' method first."
        signals = self.train_report['Probability'].values[(self.train_report['Label']==1).values]
        iron = Flattener(signals)

        popularity = pd.DataFrame()
        popularity['Name'] = self.train_report['Name']
        popularity['Popularity'] = iron(self.train_report['Probability'].values)
        popularity['Label'] = self.train_report['Label'].values
        self.popularity = popularity

        return popularity

    def roc_curve(self):
        """
        Show the classifier's ROC curve
        :return: float64 square under ROC curve value and shows ROC curve for the classifier
        """
        assert self.train_report is not None, "Use 'train()' method first."

        fpr, tpr, _ = roc_curve(self.train_report['Label'], self.train_report['Probability'], pos_label=None, sample_weight=None)
        roc_auc = auc(fpr, tpr)

        plt.figure()
        plt.subplot(1,1,1)
        plt.plot(fpr, tpr, label='auc = '+str(roc_auc), color='r')
        plt.title('ROC curve')
        plt.xlabel('False Positive Rate')
        plt.ylabel('True Positive Rate')
        plt.legend(loc='best')

        return roc_auc

    def popularity_cut_fpr(self, fpr_value=0.05):
        """

        :param float64 fpr_value: false positive rate value for data sets which have label '1'
        :return: float64 popularity cut value
        """
        assert self.train_report is not None, "Use 'train()' method first."
        assert self.popularity is not None, "Use 'get_popularity()' method first."

        prob_and_pop = pd.DataFrame()
        prob_and_pop['Label'] = self.train_report['Label'].values
        prob_and_pop['Popularity'] = self.popularity['Popularity'].values
        prob_and_pop = prob_and_pop.sort(columns='Popularity', ascending=False)
        label = prob_and_pop.values[:,0]
        ones = (label==1).cumsum().astype('float64')
        zeros = (label==0).cumsum().astype('float64')
        fpr = zeros/(zeros+ones)
        if fpr_value >= fpr[-1]:
            return 0.0
        ind = fpr[fpr<=fpr_value].shape[0]
        pop_cut = prob_and_pop.values[ind,1]
        return pop_cut
