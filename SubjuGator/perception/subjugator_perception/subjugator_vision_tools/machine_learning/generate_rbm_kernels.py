import pickle

import matplotlib.pyplot as plt
import numpy as np
import sklearn.svm
from scipy.ndimage import convolve
from sklearn import linear_model, metrics
from sklearn.cross_validation import train_test_split
from sklearn.neural_network import BernoulliRBM
from sklearn.pipeline import Pipeline
from subjugator_vision_tools import machine_learning as ml

"""
To RBM for sub...
    - Break segmented image into 8x8 sections
    - binary label sections as x or not x

"""

print(__doc__)

# Authors: Yann N. Dauphin, Vlad Niculae, Gabriel Synnaeve
# License: BSD

#
# Setting up


def nudge_dataset(X, Y):
    """
    This produces a dataset 5 times bigger than the original one,
    by moving the 8x8 images in X around by 1px to left, right, down, up
    """
    direction_vectors = [
        [[0, 1, 0], [0, 0, 0], [0, 0, 0]],
        [[0, 0, 0], [1, 0, 0], [0, 0, 0]],
        [[0, 0, 0], [0, 0, 1], [0, 0, 0]],
        [[0, 0, 0], [0, 0, 0], [0, 1, 0]],
    ]

    def shift(x, w):
        return convolve(x.reshape((8, 8)), mode="constant", weights=w).ravel()

    X = np.concatenate(
        [X] + [np.apply_along_axis(shift, 1, X, vector) for vector in direction_vectors]
    )
    Y = np.concatenate([Y for _ in range(5)], axis=0)
    return X, Y


# Load Data
# digits = datasets.load_digits()
data = pickle.load(open("segments.p", "rb"))
ims, lbls = ml.utils.make_dataset(data)
print(ims.shape)
imsz = np.reshape(ims.transpose(), (-1, ims.shape[1] * ims.shape[1]))
X, Y = ml.utils.desample_binary(imsz, lbls)
print(X.shape, Y.shape)
print(np.sum(Y == 0))
print(np.sum(Y == 1))

# X = np.asarray(digits.data, 'float32')
X, Y = nudge_dataset(X, Y)
X = (X - np.min(X, 0)) / (np.max(X, 0) + 0.0001)  # 0-1 scaling

X_train, X_test, Y_train, Y_test = train_test_split(X, Y, test_size=0.2, random_state=0)

# Models we will use
logistic = linear_model.LogisticRegression()
rbm = BernoulliRBM(random_state=0, verbose=True)
svc = sklearn.svm.SVC()

# classifier = Pipeline(steps=[('rbm', rbm), ('logistic', logistic)])
classifier = Pipeline(steps=[("rbm", rbm), ("svc", svc)])


#
# Training

# Hyper-parameters. These were set by cross-validation,
# using a GridSearchCV. Here we are not performing cross-validation to
# save time.
rbm.learning_rate = 0.06
rbm.n_iter = 20
# More components tend to give better prediction performance, but larger
# fitting time
rbm.n_components = 100
logistic.C = 6000.0

# Training RBM-Logistic Pipeline
classifier.fit(X_train, Y_train)

# Training Logistic regression
logistic_classifier = linear_model.LogisticRegression(C=100.0)
logistic_classifier.fit(X_train, Y_train)

#
# Evaluation

print()
print(
    "Logistic regression using RBM features:\n%s\n"
    % (metrics.classification_report(Y_test, classifier.predict(X_test)))
)

print(
    "Logistic regression using raw pixel features:\n%s\n"
    % (metrics.classification_report(Y_test, logistic_classifier.predict(X_test)))
)

#
# Plotting

plt.figure(figsize=(4.2, 4))
for i, comp in enumerate(rbm.components_):
    plt.subplot(10, 10, i + 1)
    plt.imshow(comp.reshape((8, 8)), cmap=plt.cm.gray_r, interpolation="nearest")
    plt.xticks(())
    plt.yticks(())
plt.suptitle("100 components extracted by RBM", fontsize=16)
plt.subplots_adjust(0.08, 0.02, 0.92, 0.85, 0.08, 0.23)

pickle.dump((classifier, rbm), open("rbm.p", "wb"))

plt.show()
