# -*- coding: utf-8 -*-
import os
import tempfile
import shutil
from io import BytesIO
import random
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from .utils import versioned_reverse as reverse
from django.test.utils import override_settings
from PIL import Image as PILImage

from .utils import get, assert_fields_exist
from events.models import Image


temp_dir = tempfile.mkdtemp()


@pytest.yield_fixture(autouse=True)
def tear_down():
    yield
    shutil.rmtree(temp_dir, ignore_errors=True)


# === util methods ===


def create_in_memory_image_file(name='test_image', image_format='png', size=(512, 256), color=(128, 128, 128)):
    image = PILImage.new('RGBA', size=size, color=color)
    file = BytesIO()
    file.name = '{}.{}'.format(name, image_format)
    image.save(file, format=image_format)
    file.seek(0)
    return file


def get_list(api_client):
    list_url = reverse('image-list')
    return get(api_client, list_url)


def get_detail(api_client, detail_pk):
    detail_url = reverse('image-detail', kwargs={'pk': detail_pk})
    return get(api_client, detail_url)


def assert_image_fields_exist(data):
    fields = (
        '@context',
        '@id',
        '@type',
        'publisher',
        'created_time',
        'cropping',
        'id',
        'url',
        'last_modified_by',
        'last_modified_time',
    )
    assert_fields_exist(data, fields)


# === fixtures ===


@pytest.fixture
def list_url():
    return reverse('image-list')


@pytest.fixture
def image_data():
    image_file = create_in_memory_image_file()
    return {
        'image': image_file,
    }


@pytest.fixture
def image_url():
    url = 'https://commons.wikimedia.org/wiki/File:Common_Squirrel.jpg'
    return {
        'url': url,
    }


# === tests ===


@pytest.mark.django_db
def test__get_image_list_check_fields_exist(api_client):
    image_file = create_in_memory_image_file(name='existing_test_image')
    uploaded_image = SimpleUploadedFile(
        'existing_test_image.png',
        image_file.read(),
        'image/png',
    )
    Image.objects.create(image=uploaded_image)
    response = get_list(api_client)
    assert_image_fields_exist(response.data['data'][0])


@pytest.mark.django_db
def test__get_image_list_check_fields_exist_for_url(api_client):
    Image.objects.create(url='https://commons.wikimedia.org/wiki/File:Common_Squirrel.jpg')
    response = get_list(api_client)
    assert_image_fields_exist(response.data['data'][0])


@pytest.mark.django_db
def test__get_detail_check_fields_exist(api_client):
    image_file = create_in_memory_image_file(name='existing_test_image')
    uploaded_image = SimpleUploadedFile(
        'existing_test_image.png',
        image_file.read(),
        'image/png',
    )
    existing_image = Image.objects.create(image=uploaded_image)
    response = get_detail(api_client, existing_image.pk)
    assert_image_fields_exist(response.data)


@pytest.mark.django_db
def test_get_detail_check_fields_exist_for_url(api_client):
    existing_image = Image.objects.create(url='https://commons.wikimedia.org/wiki/File:Common_Squirrel.jpg')
    response = get_detail(api_client, existing_image.pk)
    assert_image_fields_exist(response.data)


@pytest.mark.django_db
def test__get_detail_check_image_url(api_client):
    image_file = create_in_memory_image_file(name='existing_test_image')
    uploaded_image = SimpleUploadedFile(
        'existing_test_image.png',
        image_file.read(),
        'image/png',
    )
    existing_image = Image.objects.create(image=uploaded_image)
    response = get_detail(api_client, existing_image.pk)
    assert 'images/existing_test_image' in response.data['url']
    assert response.data['url'].endswith('.png')


@pytest.mark.django_db
def test__unauthenticated_user_cannot_upload_an_image(api_client, list_url, image_data, user):
    response = api_client.post(list_url, image_data)
    assert response.status_code == 401


@pytest.mark.django_db
def test__unauthenticated_user_cannot_upload_an_url(api_client, list_url, image_url, user):
    response = api_client.post(list_url, image_url)
    assert response.status_code == 401


@override_settings(MEDIA_ROOT=temp_dir, MEDIA_URL='')
@pytest.mark.django_db
def test__upload_an_image(api_client, settings, list_url, image_data, user):
    api_client.force_authenticate(user)

    response = api_client.post(list_url, image_data)
    assert response.status_code == 201
    assert Image.objects.all().count() == 1

    image = Image.objects.get(pk=response.data['id'])
    assert image.created_by == user
    assert image.last_modified_by == user

    # image url should contain the image file's path relative to MEDIA_ROOT.
    assert image.image.url.startswith('images/test_image')
    assert image.image.url.endswith('.png')

    # check the actual image file
    image_path = os.path.join(settings.MEDIA_ROOT, image.image.url)
    image = PILImage.open(image_path)
    assert image.size == (512, 256)
    assert image.format == 'PNG'


@pytest.mark.django_db
def test__upload_an_url(api_client, settings, list_url, image_url, user):
    api_client.force_authenticate(user)

    response = api_client.post(list_url, image_url)
    assert response.status_code == 201
    assert Image.objects.all().count() == 1

    image = Image.objects.get(pk=response.data['id'])
    assert image.created_by == user
    assert image.last_modified_by == user

    # image url should stay the same as when input
    assert image.url == 'https://commons.wikimedia.org/wiki/File:Common_Squirrel.jpg'


@pytest.mark.django_db
def test__upload_an_image_and_url(api_client, settings, list_url, image_data, image_url, user):
    api_client.force_authenticate(user)

    image_data_and_url = image_data.copy()
    image_data_and_url.update(image_url)
    response = api_client.post(list_url, image_data_and_url)
    assert response.status_code == 400
    for line in response.data:
        assert 'You can only provide image or url, not both' in line


@override_settings(MEDIA_ROOT=temp_dir, MEDIA_URL='')
@pytest.mark.django_db(transaction=True)  # transaction is needed for django-cleanup
def test__delete_an_image(api_client, settings, user):
    api_client.force_authenticate(user)

    image_file = create_in_memory_image_file(name='existing_test_image')
    uploaded_image = SimpleUploadedFile(
        'existing_test_image.png',
        image_file.read(),
        'image/png',
    )
    existing_image = Image.objects.create(image=uploaded_image)
    assert Image.objects.all().count() == 1

    # verify that the image file exists at first just in case
    image_path = os.path.join(settings.MEDIA_ROOT, existing_image.image.url)
    assert os.path.isfile(image_path)

    detail_url = reverse('image-detail', kwargs={'pk': existing_image.pk})
    response = api_client.delete(detail_url)
    assert response.status_code == 204
    assert Image.objects.all().count() == 0

    # check that the image file is deleted
    assert not os.path.isfile(image_path)


@override_settings(MEDIA_ROOT=temp_dir, MEDIA_URL='')
@pytest.mark.django_db
def test__upload_a_non_valid_image(api_client, list_url, user):
    api_client.force_authenticate(user)

    non_image_file = BytesIO(bytes(random.getrandbits(8) for _ in range(100)))

    response = api_client.post(list_url, {'image': non_image_file})
    assert response.status_code == 400
    assert 'image' in response.data


@pytest.mark.django_db
def test__upload_an_invalid_dict(api_client, list_url, user):
    api_client.force_authenticate(user)
    response = api_client.post(list_url, {'key': 'wrong'})
    assert response.status_code == 400
    for line in response.data:
        assert 'You must provide either image or url' in line