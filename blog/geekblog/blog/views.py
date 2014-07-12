#-*- coding: UTF-8 -*-
import logging
from django.conf import settings
from django.template import RequestContext
from django.shortcuts import render_to_response
from django.utils.translation import ugettext_lazy as _

from blogcore.utils import safe_cast
from blogcore.db import timestamp2datetime
from blogcore.db.blog import BlogMongodbStorage
from blogcore.models.constants import ALL_MONTHS, LINK_TYPES

blog_db = BlogMongodbStorage(settings.MONGODB_CONF)
logger = logging.getLogger('geekblog')

DATE_FORMAT = '%Y-%m-%d'


def _get_month_and_day(p_date):
    infos = {'year': '1990', 'month': '01', 'day': '01', 'month_str': ALL_MONTHS[0], 'publish_date_str': ''}
    if not p_date or not isinstance(p_date, long):
        return infos
    date = timestamp2datetime(p_date, convert_to_local=True).date()
    date_str = date.strftime(DATE_FORMAT)
    infos['year'], infos['month'], infos['day'] = date_str.split('-')
    infos['month_str'], infos['publish_date_str'] = ALL_MONTHS[date.month - 1], date_str
    return infos


def _process_single_article(article):
    # process article infos and format the data with rules.
    article.update(_get_month_and_day(article.get('publish_date', None)))
    return article


def _process_articles(articles):
    for article in articles:
        _process_single_article(article)
    return articles


def _get_start_index(page_num):
    page_num = safe_cast(page_num, int)
    if page_num is None:
        page_num = 1
    return settings.LIST_PER_PAGE * (page_num - 1)


def _render_response(request, template_name, context):
    if context:
        context.update({'all_tags': blog_db.get_tags(), 'newest_articles': blog_db.get_newest_articles(has_login=(not request.user.is_anonymous()))})

    return render_to_response(template_name, context, context_instance=RequestContext(request))


def _render_404_response(request):
    return _render_response(request, '404.html', {})


def show_homepage(request, page_num):
    start_index = _get_start_index(page_num)
    article_infos = blog_db.get_articles({}, start_index=start_index, count=settings.LIST_PER_PAGE, has_login=(not request.user.is_anonymous()), with_total=True)

    context_infos = {
        'sliders': blog_db.get_all_sliders(),
        'current_page': page_num,
        'total_page': article_infos['page_count'],
        'articles': _process_articles(article_infos['results']),
    }
    return _render_response(request, 'index.html', context_infos)


def show_article(request, a_id):
    article_infos = blog_db.get_article_by_id(a_id)
    # if article_infos is None or this article can only be viewed by logined user
    if not article_infos or (request.user.is_anonymous() and article_infos['login_required']):
        logger.exception('Invaild article ID: %s' % a_id)
        return _render_404_response(request)

    # update articel views_count
    blog_db.increment_article_views_count(a_id)
    # get previous and next articles
    prev_a = blog_db.get_prev_article(a_id)
    next_a = blog_db.get_next_article(a_id)

    context_infos = {
        'page_title': article_infos['title'],
        'prev_a': prev_a,
        'next_a': next_a,
    }
    context_infos.update(_process_single_article(article_infos))
    return _render_response(request, 'detail.html', context_infos)


def show_category(request, cate_slug, page_num):
    cate_infos = blog_db.get_cate_info_by_slug(cate_slug)
    if not cate_infos:
        logger.exception('Invaild category slug: %s' % cate_slug)
        return _render_404_response(request)

    start_index = _get_start_index(page_num)
    article_infos = blog_db.get_cate_articles(cate_infos['id'], start_index=start_index, count=settings.LIST_PER_PAGE, has_login=(not request.user.is_anonymous()), with_total=True)

    context_infos = {
        'page_title': cate_infos['name'],
        'sliders': blog_db.get_all_sliders(),
        'current_page': page_num or 1,
        'total_page': article_infos['page_count'],
        'articles': _process_articles(article_infos['results']),
    }
    return _render_response(request, 'index.html', context_infos)


def show_tag(request, tag_slug, page_num):
    tag_infos = blog_db.get_tag_info_by_slug(tag_slug)
    if not tag_infos:
        logger.exception('Invaild tag slug: %s' % tag_slug)
        return _render_404_response(request)

    start_index = _get_start_index(page_num)
    article_infos = blog_db.get_tag_articles(tag_infos['id'], start_index=start_index, count=settings.LIST_PER_PAGE, has_login=(not request.user.is_anonymous()), with_total=True)

    context_infos = {
        'page_title': tag_infos['name'],
        'sliders': blog_db.get_all_sliders(),
        'current_page': page_num or 1,
        'total_page': article_infos['page_count'],
        'articles': _process_articles(article_infos['results']),
    }
    return _render_response(request, 'index.html', context_infos)


def show_search(request, keyword, page_num):
    # format the keyword, remove unusable char.
    keyword = keyword.replace('/', '').strip()
    start_index = _get_start_index(page_num)

    article_infos = blog_db.search_articles(keyword, start_index=start_index, count=settings.LIST_PER_PAGE, has_login=(not request.user.is_anonymous()), with_total=True)

    context_infos = {
        'page_title': keyword,
        'sliders': blog_db.get_all_sliders(),
        'current_page': page_num or 1,
        'total_page': article_infos['page_count'],
        'articles': _process_articles(article_infos['results']),
    }
    return _render_response(request, 'index.html', context_infos)


def show_archive_page(request):
    articles = blog_db.get_articles({}, count=10000, fields={'_id': 0, 'id': 1, 'title': 1, 'publish_date': 1}, has_login=(not request.user.is_anonymous()), with_total=True)
    archives = {}
    # format the data of archives for template
    for article in _process_articles(articles['results']):
        year, month = article['year'], article['month']
        if year in archives:
            if month in archives[year]:
                archives[year][month].append(article)
            else:
                archives[year][month] = [article]
        else:
            archives[year] = {month: [article]}

    context_infos = {
        'page_title': _('Archive'),
        'archives': archives,
        'total_num': articles['total'],
    }
    return _render_response(request, 'archive.html', context_infos)


def show_about_page(request):
    return _render_response(request, 'about.html', {'page_title': _('About')})


def show_friend_link_page(request):
    all_links = blog_db.get_all_links()
    friend_links = [link for link in all_links if link['type'] == LINK_TYPES.FRIEND_LINK]
    site_links = [link for link in all_links if link['type'] == LINK_TYPES.SITE_LINK]

    context_infos = {
        'page_title': _('Friend Links'),
        'friend_links': friend_links,
        'site_links': site_links,
    }
    return _render_response(request, 'link.html', context_infos)
