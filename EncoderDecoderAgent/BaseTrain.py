import random
import torch
import torch.nn.functional as F

from EncoderDecoderAgent.ReplayMemory import ReplayMemory, Transition

from itertools import count
from tqdm import tqdm
import math

from pathlib import Path

from PatternDetectionInCandleStick.Evaluation import Evaluation

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")


class BaseTrain:
    def __init__(self, data_loader, data_train, data_test, dataset_name, model_kind, transaction_cost=0.0,
                 BATCH_SIZE=30, GAMMA=0.7, EPS=0.1, ReplayMemorySize=50, TARGET_UPDATE=5,
                 n_actions=3, n_step=10, window_size=20):
        """
        :param TARGET_UPDATE: Every TARGET_UPDATE iterations, we give the weights of the Policy network to the Target
                                network.
        :param n_step: n in n-step SARSA
        """
        print(model_kind)
        self.data_train = data_train
        self.data_test = data_test
        self.DATASET_NAME = dataset_name
        self.BATCH_SIZE = BATCH_SIZE
        self.GAMMA = GAMMA
        self.EPS = EPS
        self.ReplayMemorySize = ReplayMemorySize
        self.window_size = window_size
        self.model_kind = model_kind

        self.split_point = data_loader.split_point
        self.begin_date = data_loader.begin_date
        self.end_date = data_loader.end_date

        self.TARGET_UPDATE = TARGET_UPDATE
        self.n_actions = n_actions
        self.n_step = n_step
        self.transaction_cost = transaction_cost

        self.memory = ReplayMemory(ReplayMemorySize)

        self.train_test_split = True if data_test is not None else False

        self.EPS_START = 0.9
        self.EPS_END = 0.05
        self.EPS_DECAY = 500

        self.steps_done = 0

    def select_action(self, state):
        sample = random.random()

        eps_threshold = self.EPS_END + (self.EPS_START - self.EPS_END) * \
                        math.exp(-1. * self.steps_done / self.EPS_DECAY)
        self.steps_done += 1

        # eps_threshold = self.EPS

        if sample > eps_threshold:
            with torch.no_grad():
                # t.max(1) will return largest column value of each row.
                # second column on max result is index of where max element was
                # found, so we pick action with the larger expected reward.
                self.policy_net.eval()
                action = self.policy_net(state)
                action = action.max(1)[1].view(1, 1)
                self.policy_net.train()
                return action
        else:
            return torch.tensor([[random.randrange(self.n_actions)]], device=device, dtype=torch.long)

    def optimize_model(self):
        if len(self.memory) < self.BATCH_SIZE:
            return
        transitions = self.memory.sample(self.BATCH_SIZE)
        # Transpose the batch (see https://stackoverflow.com/a/19343/3343043 for
        # detailed explanation). This converts batch-array of Transitions
        # to Transition of batch-arrays.
        batch = Transition(*zip(*transitions))

        # Compute a mask of non-final states and concatenate the batch elements
        # (a final state would've been the one after which simulation ended)
        non_final_mask = torch.tensor(tuple(map(lambda s: s is not None,
                                                batch.next_state)), device=device, dtype=torch.bool)

        # For GRU input, the second argument shows the batch_size, thus dim = 1
        non_final_next_states = torch.cat([s for s in batch.next_state
                                           if s is not None], dim=1)

        # For GRU input, the second argument shows the batch_size, thus dim = 1
        state_batch = torch.cat(batch.state, dim=1)
        action_batch = torch.cat(batch.action)
        reward_batch = torch.cat(batch.reward)
        # Compute Q(s_t, a) - the model computes Q(s_t), then we select the
        # columns of actions taken. These are the actions which would've been taken
        # for each batch state according to policy_net

        # Using policy-net, we calculate the action-value of the previous actions we have taken before.
        state_action_values = self.policy_net(state_batch)
        state_action_values = state_action_values.gather(1, action_batch)
        # Compute V(s_{t+1}) for all next states.
        # Expected values of actions for non_final_next_states are computed based
        # on the "older" target_net; selecting their best reward with max(1)[0].
        # This is merged based on the mask, such that we'll have either the expected
        # state value or 0 in case the state was final.
        next_state_values = torch.zeros(self.BATCH_SIZE, device=device)
        next_state_values_temp = self.target_net(non_final_next_states)
        next_state_values[non_final_mask] = next_state_values_temp.max(1)[0].detach()
        # Compute the expected Q values

        expected_state_action_values = (next_state_values * (self.GAMMA ** self.n_step)) + reward_batch

        # Compute Huber loss
        loss = F.smooth_l1_loss(state_action_values, expected_state_action_values.unsqueeze(1))

        # Optimize the model
        self.optimizer.zero_grad()

        loss.backward()
        for param in self.policy_net.parameters():
            param.grad.data.clamp_(-1, 1)

        # for name, param in self.encoder.named_parameters():
        #     print(name)
        #     print(param.grad.data.sum())
        #     print('*' * 100)

        self.optimizer.step()

        return loss

    def train(self, num_episodes=50, tensorboard=None):
        for i_episode in tqdm(range(num_episodes)):
            # Initialize the environment and state
            total_loss = 0
            self.data_train.reset()
            state = self.data_train.get_current_state()
            for t in count():
                # Select and perform an action
                action = self.select_action(state)
                done, reward, next_state = self.data_train.step(action.item())

                reward = torch.tensor([reward], dtype=torch.float, device=device)

                # if next_state is not None:
                #     next_state = torch.tensor([next_state], dtype=torch.float, device=device)

                # Store the transition in memory
                self.memory.push(state, action, next_state, reward)

                # Move to the next state
                if not done:
                    state = self.data_train.get_current_state()

                # Perform one step of the optimization (on the target network)
                loss = self.optimize_model()
                if loss is not None:
                    total_loss += loss.item()

                if done:
                    break
            # Update the target network, copying all weights and biases in DQN
            if i_episode % self.TARGET_UPDATE == 0:
                self.target_net.load_state_dict(self.policy_net.state_dict())

            self.data_train.reset()
            action_list = []
            self.data_train.__iter__()
            for batch in self.data_train:
                try:
                    action_batch = self.policy_net(batch)
                    action_batch = action_batch.max(1)[1]
                    action_list += list(action_batch.cpu().numpy())
                except ValueError:
                    action_list += [1]  # None

            total_reward = self.data_train.get_total_reward(action_list)

            if tensorboard is not None:
                tensorboard.add_scalar(f'Loss', total_loss, i_episode)
                tensorboard.add_scalar(f'TotalReward', total_reward, i_episode)

        self.save_model(self.policy_net.state_dict())

        print('Complete')

    def save_model(self, model):

        experiment_num = 1
        import os
        PATH = os.path.join(Path(os.path.abspath(os.path.dirname(__file__))).parent,
                            f'Objects/{self.model_kind}') + '/'

        if not os.path.exists(PATH):
            os.makedirs(PATH)

        while os.path.exists(
                f'{PATH}{self.DATASET_NAME}; DATA_KIND({self.data_train.data_kind}); '
                f'Dates({self.begin_date}, {self.split_point}, {self.end_date}); {self.model_kind}; '
                f'TC({self.transaction_cost}); WindowSize({self.window_size}); '
                f'BATCH_SIZE{self.BATCH_SIZE}; GAMMA{self.GAMMA}; EPS{self.EPS}; '
                f'REPLAY_MEMORY_SIZE{self.ReplayMemorySize}; C{self.TARGET_UPDATE}; N_SARSA{self.n_step}({experiment_num}).pkl'):
            experiment_num += 1

        file_name = (f'{PATH}{self.DATASET_NAME}; DATA_KIND({self.data_train.data_kind}); '
                     f'Dates({self.begin_date}, {self.split_point}, {self.end_date}); {self.model_kind}; '
                     f'TC({self.transaction_cost}); WindowSize({self.window_size}); '
                     f'BATCH_SIZE{self.BATCH_SIZE}; GAMMA{self.GAMMA}; EPS{self.EPS}; '
                     f'REPLAY_MEMORY_SIZE{self.ReplayMemorySize}; C{self.TARGET_UPDATE}; '
                     f'N_SARSA{self.n_step}({experiment_num}).pkl')

        torch.save(model, file_name)
        self.model_file_name = file_name

    def test(self, file_name, action_name, initial_investment=1000, test_type='train'):
        """
        :param file_name: name of the .pkl file to load the model
        :param test_type: test results on train data or test data
        :return:
        """
        if file_name is None:
            file_path = self.model_file_name
        else:
            import os
            file_path = os.path.join(Path(os.path.abspath(os.path.dirname(__file__))).parent,
                                     f'Objects/{self.model_kind}/{file_name}')

        data = self.data_train if test_type == 'train' else self.data_test

        self.test_net.load_state_dict(torch.load(file_path))
        self.test_net.to(device)

        action_list = []
        data.__iter__()
        for batch in data:
            try:
                action_batch = self.test_net(batch)
                action_batch = action_batch.max(1)[1]
                action_list += list(action_batch.cpu().numpy())
            except ValueError:
                action_list += [1]  # None

        data.make_investment(action_list)
        ev_agent = Evaluation(data.data, action_name, initial_investment, self.transaction_cost)
        print(test_type)
        ev_agent.evaluate()
        return ev_agent
