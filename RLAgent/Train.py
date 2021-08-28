import pickle
import pandas as pd

# from ..PatternDetectionInCandleStick.LabelPatterns import label_candles
# from .FirstAgent import Agent
from .Agent import Agent

from PatternDetectionInCandleStick.LabelPatterns import label_candles
from PatternDetectionInCandleStick.Evaluation import Evaluation

# from FirstAgent import Agent
# from SecondAgent import Agent

from pathlib import Path
import warnings
from tqdm import tqdm


class Train:
    def __init__(self, data_train, data_test, patterns, dataset_name, n=5, num_iteration=10000,
                 gamma=1, alpha=0.3,
                 epsilon=0.01):
        self.data_train = data_train
        self.data_test = data_test
        self.agent = Agent(self.data_train, patterns, n, gamma, alpha, epsilon)
        self.num_iteration = num_iteration
        self.DATASET_NAME = dataset_name

        self.n = n
        self.gamma = gamma
        self.epsilon = epsilon
        self.alpha = alpha
        self.train_test_split = True if data_test is not None else False

    def training(self):
        for _ in tqdm(range(self.num_iteration)):
            self.agent.value_iteration()

    def write_to_file(self):
        experiment_num = 1
        import os
        PATH = os.path.join(Path(os.path.abspath(os.path.dirname(__file__))).parent, f'Objects/RLAgent') + '/'

        while os.path.exists(
                f'{PATH}{self.DATASET_NAME}-TRAIN_TEST_SPLIT({self.train_test_split})-NUM_ITERATIONS{self.num_iteration}-N_STEP{self.n}-GAMMA{self.gamma}-ALPHA{self.alpha}-EPSILON{self.epsilon}-EXPERIMENT({experiment_num}).pkl'):
            experiment_num += 1

        with open(
                f'{PATH}{self.DATASET_NAME}-TRAIN_TEST_SPLIT({self.train_test_split})-NUM_ITERATIONS{self.num_iteration}-N_STEP{self.n}-GAMMA{self.gamma}-ALPHA{self.alpha}-EPSILON{self.epsilon}-EXPERIMENT({experiment_num}).pkl',
                'wb') as output:
            pickle.dump(self.agent, output, pickle.HIGHEST_PROTOCOL)

    def read_from_file(self, filename):
        import os
        PATH = os.path.join(Path(os.path.abspath(os.path.dirname(__file__))).parent, f'Objects/RLAgent') + '/'

        with open(PATH + filename, 'rb') as input:
            self.agent = pickle.load(input)

    def test(self, test_type='train'):
        self.make_investment(self.data_train)
        if self.data_test is not None:
            self.make_investment(self.data_test)
            return Evaluation(self.data_train if test_type == 'train' else self.data_test, 'action_agent', 1000)
        else:
            return Evaluation(self.data_train, 'action_agent', 1000)

    def make_investment(self, data):
        data['action_agent'] = 'None'
        i = 0
        for a in iter(self.agent.take_action_with_policy(data)):
            data['action_agent'][i] = convert_number_to_action(a)
            i += 1


def convert_number_to_action(a):
    if a == 0:
        return 'buy'
    elif a == 2:
        return 'sell'
    else:
        return 'None'


def load_data(data_path):
    warnings.filterwarnings('ignore')
    data = pd.read_csv(data_path, date_parser=True)
    data.dropna(inplace=True)
    data.timestamp = pd.to_datetime(data.timestamp.str.replace('D', 'T'))
    data = data.sort_values('timestamp')
    data.set_index('timestamp', inplace=True)

    # data = data[-100:]

    data = (data.resample('D')
            .agg({'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last'}))
    # data['mean_candle'] = (data.close + data.open) / 2
    data['mean_candle'] = data.close
    data.reset_index(drop=True, inplace=True)
    patterns = label_candles(data)
    return data, list(patterns.keys())

