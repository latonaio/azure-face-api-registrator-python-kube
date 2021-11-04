#!/usr/bin/env python3
# coding: utf-8

# Copyright (c) Latona. All rights reserved.
import asyncio
import os
import datetime
from io import BytesIO
import json
import time
import sys
import logging

# Azure Face API用モジュール
from azure.cognitiveservices.vision.face import FaceClient
from msrest.authentication import CognitiveServicesCredentials
from azure.cognitiveservices.vision.face.models import TrainingStatusType
# RabbitMQ用モジュール
from rabbitmq_client import RabbitmqClient
# JSONロギング用モジュール
from custom_logger import init_logger

from PIL import ImageDraw, Image

SERVICE_NAME = 'azure-face-api-registrator-kube'
PERSON_GROUP_ID = ''
logger = logging.getLogger(__name__)



class FaceRecognition():
    def __init__(self):
        with open('face-api-config.json', 'r') as f:
            settings = json.load(f)

        # set PERSON_GROUP_ID from face-api-config.json
        global PERSON_GROUP_ID
        PERSON_GROUP_ID = settings.get('PERSON_GROUP_ID')

        # Create an authenticated FaceClient.
        self.face_client = FaceClient(
            settings.get('API_ENDPOINT'),
            CognitiveServicesCredentials(settings.get('API_ACCESS_KEY'))
        )

    def getFaceAttributes(self, imagePath):
        params = ['gender', 'age']
        # return self.face_client.person_group_person.get(PERSON_GROUP_ID, personId)
        with open(imagePath, 'rb') as image_data:
            return self.face_client.face.detect_with_stream(
                image_data, return_face_attributes=params
            )

    def createPersonGroup(self):
        logging.debug('Create person group ' + PERSON_GROUP_ID)
        self.face_client.person_group.create(
            person_group_id=PERSON_GROUP_ID,
            name=PERSON_GROUP_ID
        )

    def deletePersonGroup(self):
        logging.debug('Delete person group ' + PERSON_GROUP_ID)
        self.face_client.person_group.delete(
            person_group_id=PERSON_GROUP_ID
        )

    def createPerson(self, name):
        logging.debug('Create person')
        person = self.face_client.person_group_person.create(PERSON_GROUP_ID, name=name)
        return person.person_id

    def getPersonList(self):
        logging.debug('get person list')
        persons = self.face_client.person_group_person.list(PERSON_GROUP_ID)
        for person in persons:
            logging.debug(person)
        return persons

    def getPerson(self, personId):
        logging.debug('Get person ' + personId)
        person = self.face_client.person_group_person.get(PERSON_GROUP_ID, personId)
        return person

    def setPersonImage(self, personId, imagePath, targetFace=None):
        logger.debug('Set person image ' + imagePath)
        with open(imagePath, 'r+b') as image:
            self.face_client.person_group_person.add_face_from_stream(
                PERSON_GROUP_ID, personId, image, targetFace)

    def train(self):
        # Train the person group
        self.face_client.person_group.train(PERSON_GROUP_ID)

        logger.debug('Training the person group...')
        while True:
            training_status = self.face_client.person_group.get_training_status(PERSON_GROUP_ID)
            logging.info('Training status: {}.'.format(training_status.status))
            if (training_status.status is TrainingStatusType.succeeded):
                break
            elif (training_status.status is TrainingStatusType.failed):
                logger.error('Failed to train ...')
                raise Exception('Training the person group has failed.')
            time.sleep(1)

    def getPersonIdFromImage(self, faceImage):
        logging.debug(faceImage)

        # Detect faces
        face_ids = []
        with open(faceImage, 'r+b') as image:
            faces = self.face_client.face.detect_with_stream(image)
        for face in faces:
            logging.info(face)
            face_ids.append(face.face_id)

        return self.face_client.face.identify(face_ids, PERSON_GROUP_ID)


def getRectangle(face_rectangle):
    rect = face_rectangle
    left = rect.left
    top = rect.top
    right = left + rect.width
    bottom = top + rect.height

    return (left, top, right, bottom)


async def main():
    init_logger()

    # RabbitMQの接続情報
    rabbitmq_url = os.environ['RABBITMQ_URL']
    # キューの読み込み元
    queue_origin = os.environ['QUEUE_ORIGIN']
    # キューの書き込み先
    queue_to = os.environ['QUEUE_TO']

    try:
        mq_client = await RabbitmqClient.create(rabbitmq_url, {queue_origin}, {queue_to})
    except Exception as e:
        logger.error({
            'message': 'failed to connect rabbitmq!',
            'error': str(e),
            'queue_origin': queue_origin,
            'queue_to': queue_to,
        })
        # 本来 sys.exit を使うべきだが、効かないので
        os._exit(1)

    logger.info('create mq client')

    async for message in mq_client.iterator():
        try:
            async with message.process():
                logger.info({
                    'message': 'received from: ' + message.queue_name,
                    'params': message.data,
                })
                guest_id = message.data.get('guest_id')
                filepath = message.data.get('face_image_path')
                output_path = message.data.get('output_data_path')

                fr = FaceRecognition()
                person_list = fr.getPersonList()
                ids = len(person_list)
                person = fr.getFaceAttributes(filepath)
                # 一番大きい顔を選ぶ
                attributes = {
                    'gender': str(person[0].face_attributes.gender).lstrip('Gender.'),
                    'age': str(person[0].face_attributes.age)
                }
                now = datetime.datetime.now()
                tmp_file = os.path.join(output_path, now.strftime('%Y%m%d_%H%M%S') + '.jpg')
                image_data = Image.open(filepath)
                image_data.crop(getRectangle(person[0].face_rectangle)).save(tmp_file, quality=95)
                name = now.strftime('%Y%m%d_%H%M%S')
                person_id = fr.createPerson(ids)
                fr.setPersonImage(person_id, tmp_file, person[0].face_rectangle)
                fr.train()
                os.remove(tmp_file)

                payload = {
                    'result': True,
                    'filepath': filepath,
                    'guest_id': guest_id,
                    'face_id_azure': str(person_id),
                    'attributes': attributes,
                }
                logger.debug({
                    'message': 'send message',
                    'params': payload,
                })
                await mq_client.send(queue_to, payload)
                logger.info('sent message')
        except Exception as e:
            logger.error({
                'message': 'error with processing message',
                'error': str(e),
            })

if __name__ == '__main__':
    asyncio.run(main())

