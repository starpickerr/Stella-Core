#!/bin/bash

unset KUBECONFIG

cd .. && docker build -f docker/Dockerfile.latest \
             -t starpickerr/stella .

docker tag starpickerr/stella starpickerr/stella:$(date +%y%m%d)