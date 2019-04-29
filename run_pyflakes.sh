#!/bin/bash


find zeus_ci | grep \.py$ | pyflakes zeus_ci/
