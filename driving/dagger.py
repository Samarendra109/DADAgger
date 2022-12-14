import pickle

import imageio
import numpy as np
import torch

import train_policy
import racer
import argparse
import os

from driving_policy import DropoutDrivingPolicy
from dropout_policy import DropoutPolicy
from full_state_car_racing_env import FullStateCarRacingEnv
from utils import DEVICE
import matplotlib.pyplot as plt


def run(env, steering_network, timesteps):
    env.reset()
    cross_track_error = []

    learner_action = np.array([0.0, 0.0, 0.0])

    for t in range(timesteps):
        env.render()

        state, expert_action, reward, done, _ = env.step(learner_action)
        cross_track_error.append(env.get_cross_track_error(env.car, env.track)[1])
        if done:
            break

        learner_action[0] = steering_network.predict(state / 255, device=DEVICE)[0]
        learner_action[1] = expert_action[1]
        learner_action[2] = expert_action[2]

    env.close()
    return cross_track_error


def get_cumulative_cross_track_error(cross_track_error_list):
    max_length_travelled = max(
        len(cross_track_errors) for cross_track_errors in cross_track_error_list
    )
    cumulative_loss_list = []
    for cross_track_errors in cross_track_error_list:
        # Taking absolute value as the cross_track_error can be positive or negative based on direction of error
        #   For the vehicles who veered off the track early, their last error is taken and
        #   is repeated for the complete length (To have a better comparison with the cars that finished the track)
        cumulative_loss = sum(abs(e) for e in cross_track_errors) + abs(
            cross_track_errors[-1]
        ) * (max_length_travelled - len(cross_track_errors))
        cumulative_loss_list.append(cumulative_loss)
    return cumulative_loss_list


def get_model_class(args):
    # For now returning default value. But as we add more env,
    # we will change the return value based on command line arguments.
    return DropoutDrivingPolicy


def get_env_class(args):
    # For now returning default value. But as we add more env,
    # we will change the return value based on command line arguments.
    return FullStateCarRacingEnv


def get_env_args(args):
    # For now returning default value. But as we add more env,
    # we will change the return value based on command line arguments.
    return {}


def main(env_class, env_args, args):
    #####
    ## Enter your DAgger code here
    ## Reuse functions in racer.py and train_policy.py
    ## Save the learner weights of the i-th DAgger iteration in ./weights/learner_i.weights where
    #####

    # Default args values
    args.save_expert_actions = True
    args.expert_drives = False
    args.timesteps = 100_000
    args.weighted_loss = True
    args.folder_name = f"{args.experiment_name}_M{args.M}_alpha{args.alpha}"
    args.out_dir = f"./results/{args.folder_name}/train"
    args.train_dir = args.out_dir
    args.weights_out_file = f"./results/{args.folder_name}/learner_{0}.weights"

    if not os.path.exists(f"./{args.out_dir}"):
        os.makedirs(f"./{args.out_dir}")

    # print ('TRAINING LEARNER ON INITIAL DATASET')
    learner_policies = [train_policy.main(args)]
    cross_track_error = []

    for i in range(args.dagger_iterations):
        args.weights_out_file = f"./results/{args.folder_name}/learner_{i + 1}.weights"
        args.run_id = (
                100 + i
        )  # Adding 100 to distinguish between existing dataset and expert dataset
        # print ('GETTING EXPERT DEMONSTRATIONS')
        env = env_class(**env_args)
        racer.run(env, learner_policies[i], args)
        # print ('RETRAINING LEARNER ON AGGREGATED DATASET')
        learner_policies.append(train_policy.main(args))

    cross_track_error_list = []
    for i in range(args.dagger_iterations + 1):
        args.weights_out_file = f"./results/{args.folder_name}/learner_{i}.weights"

        driving_policy = DropoutPolicy(args.model_class, n_classes=args.n_steering_classes, M=args.M).to(
            DEVICE
        )

        driving_policy.load_state_dict(torch.load(args.weights_out_file))
        env = env_class(**env_args)
        cross_track_error_list.append(run(env, driving_policy, args.timesteps))

    with open(f"./results/{args.folder_name}/cross_track_error_list.errors", "wb") as f:
        pickle.dump(cross_track_error_list, f)

    cumulative_cross_track_errors = get_cumulative_cross_track_error(
        cross_track_error_list
    )

    with open(f"./results/{args.folder_name}/cum_cross_track_error.errors", "wb") as f:
        pickle.dump(cumulative_cross_track_errors, f)

    fig, ax = plt.subplots(nrows=1, ncols=1)
    ax.plot(
        list(range(len(cumulative_cross_track_errors))),
        cumulative_cross_track_errors,
        linestyle="--",
        marker="o",
    )
    fig.savefig(f"./results/{args.folder_name}/dataset_iterations.png")
    plt.close(fig)


if __name__ == "__main__":

    parser = argparse.ArgumentParser()
    parser.add_argument("--lr", type=float, help="learning rate", default=1e-3)
    parser.add_argument("--M", type=int, help="number of models in ensemble", default=1)
    parser.add_argument("--alpha", type=float, help="percentile", default=1)
    parser.add_argument("--n_epochs", type=int, help="number of epochs", default=25)
    parser.add_argument("--batch_size", type=int, help="batch_size", default=256)
    parser.add_argument(
        "--n_steering_classes", type=int, help="number of steering classes", default=20
    )
    parser.add_argument(
        "--train_dir", help="directory of training data", default="./dataset/train"
    )
    parser.add_argument(
        "--validation_dir", help="directory of validation data", default="./dataset/val"
    )
    parser.add_argument(
        "--experiment_name",
        help="folder to save the weights of the network, i.e, experiment name, e.g. tuning",
        default="",
    )
    parser.add_argument("--dagger_iterations", help="", default=10)
    args = parser.parse_args()

    env_class = get_env_class(args)
    env_args = get_env_args(args)

    args.model_class = get_model_class(args)

    main(env_class, env_args, args)