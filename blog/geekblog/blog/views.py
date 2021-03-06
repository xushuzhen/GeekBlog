# -*- coding: UTF-8 -*-
import logging
from django.conf import settings
from django.template import RequestContext
from django.shortcuts import render_to_response
from django.views.decorators.cache import cache_page
from django.utils.translation import ugettext, ugettext_lazy as _

from utils import safe_cast
from mongodb.blog import BlogMongodbStorage
from mongodb import datetime2timestamp, timestamp2datetime
from geek_blog.constants import ALL_MONTHS, LINK_TYPES
from blog.models import Article

logger = logging.getLogger('geekblog')
blog_db = BlogMongodbStorage(settings.MONGODB_CONF)


def _get_month_and_day(p_date):
    """ parse publish_date and get month and day """
    infos = {'year': '1990', 'month': '01', 'day': '01', 'month_str': ALL_MONTHS[0], 'publish_date_str': ''}
    if not p_date or not isinstance(p_date, long):
        return infos

    date = timestamp2datetime(p_date, convert_to_local=True).date()
    date_str = date.strftime(settings.PUBLISH_DATE_FORMAT)

    infos['year'], infos['month'], infos['day'] = date_str.split('-')
    infos['month_str'], infos['publish_date_str'] = ALL_MONTHS[date.month - 1], date_str

    return infos


def _process_single_article(article):
    # process article infos and format the data with rules.
    article.update(_get_month_and_day(article.get('publish_date', None)))

    # to disable comment when debug is on
    if settings.DEBUG:
        article.update({'enable_comment': False})

    return article


def _process_articles(articles):
    for article in articles:
        _process_single_article(article)

    return articles


def _get_start_index(page_num):
    page_num = safe_cast(page_num, int, 1)

    return settings.LIST_PER_PAGE * (page_num - 1)


def _get_pagination_infos(article_infos, page_num):
    page_num = safe_cast(page_num, int, 1)

    return {
        'current_page': page_num,
        'total_page': article_infos['page_count'],
        'has_prev': 1 < page_num <= article_infos['page_count'],
        'has_next': 1 <= article_infos['page_count'] > page_num,
    }


def _render_response(request, template_name, context, is_index=False):
    is_mobile = request.META.get('IS_MOBILE', False)
    template_path = settings.TEMPLATE_NAMES[template_name]['m' if is_mobile else 'p']
    context['is_mobile'] = is_mobile

    # update context to add all_tags and newest_articles infos when is_mobile is False
    if context and not is_mobile:
        context.update({'all_tags': blog_db.get_tags(), 'newest_articles': blog_db.get_hottest_articles(has_login=(not request.user.is_anonymous()))})
    # if page is blog list page, update slider infos
    if is_index:
        context.update({'sliders': blog_db.get_all_sliders()})

    return render_to_response(template_path, context, context_instance=RequestContext(request))


def _render_404_response(request):
    return _render_response(request, '404', {})


def show_homepage(request, page_num):
    start_index = _get_start_index(page_num)
    article_infos = blog_db.get_articles({}, start_index=start_index, count=settings.LIST_PER_PAGE, has_login=(not request.user.is_anonymous()), with_total=True)

    context_infos = {
        'articles': _process_articles(article_infos['results']),
    }
    context_infos.update(_get_pagination_infos(article_infos, page_num))

    return _render_response(request, 'index', context_infos, is_index=True)


def show_article(request, slug):
    # 兼容之前的旧URL格式
    article_infos = blog_db.get_article_by_id(slug) if str.isdigit(str(slug)) else blog_db.get_article_by_slug(slug)
    # if article_infos is None or this article can only be viewed by logined user
    if not article_infos or (request.user.is_anonymous() and article_infos['login_required']):
        logger.warning('Invaild article slug: %s' % slug)
        return _render_404_response(request)

    a_id, publish_date = article_infos.get('id', 0), article_infos.get('publish_date', 0)
    # update article views_count
    blog_db.increment_article_views_count(a_id)

    # get previous and next articles
    prev_a = blog_db.get_prev_article(publish_date)
    next_a = blog_db.get_next_article(publish_date)

    context_infos = {
        'page_title': article_infos['title'],
        'prev_a': prev_a,
        'next_a': next_a,
    }
    context_infos.update(_process_single_article(article_infos))

    return _render_response(request, 'detail', context_infos)


def preview_article(request, slug):
    try:
        article = Article.objects.get(slug__exact=slug)
    except Article.DoesNotExist:
        logger.warning('Invaild article slug: %s' % slug)
        return _render_404_response(request)

    publish_date = datetime2timestamp(article.publish_date, convert_to_utc=True)
    # get previous and next articles
    prev_a = blog_db.get_prev_article(publish_date)
    next_a = blog_db.get_next_article(publish_date)

    context_infos = {
        'page_title': article.title,
        'prev_a': prev_a,
        'next_a': next_a,
    }
    article_infos = {
        'id': article.id,
        'title': article.title,
        'slug': article.slug,
        'category_id': article.category.id,
        'category_name': article.category.name,
        'category_slug': article.category.slug,
        'description': article.description,
        'content': article.content,
        'mark': article.mark,
        'enable_comment': False,
        'login_required': article.login_required,
        'views_count': article.views_count,
        'publish_date': publish_date,
        'thumbnail_url': (article.thumbnail.path.url if article.thumbnail.path else article.thumbnail.url) if article.thumbnail else 'http://xianglong.qiniudn.com/default_article_image.gif',
        'tags': article.get_tags(),
    }
    context_infos.update(_process_single_article(article_infos))

    return _render_response(request, 'detail', context_infos)


def show_category(request, cate_slug, page_num):
    cate_infos = blog_db.get_cate_info_by_slug(cate_slug)
    if not cate_infos:
        logger.warning('Invaild category slug: %s' % cate_slug)
        return _render_404_response(request)

    start_index = _get_start_index(page_num)
    article_infos = blog_db.get_cate_articles(cate_infos['id'], start_index=start_index, count=settings.LIST_PER_PAGE,
                                              has_login=(not request.user.is_anonymous()), with_total=True)

    context_infos = {
        'page_title': cate_infos['name'],
        'articles': _process_articles(article_infos['results']),
    }
    context_infos.update(_get_pagination_infos(article_infos, page_num))

    return _render_response(request, 'index', context_infos, is_index=True)


def show_tag(request, tag_slug, page_num):
    tag_infos = blog_db.get_tag_info_by_slug(tag_slug)
    if not tag_infos:
        logger.warning('Invaild tag slug: %s' % tag_slug)
        return _render_404_response(request)

    start_index = _get_start_index(page_num)
    article_infos = blog_db.get_tag_articles(tag_infos['id'], start_index=start_index, count=settings.LIST_PER_PAGE,
                                             has_login=(not request.user.is_anonymous()), with_total=True)

    context_infos = {
        'page_title': tag_infos['name'],
        'articles': _process_articles(article_infos['results']),
    }
    context_infos.update(_get_pagination_infos(article_infos, page_num))

    return _render_response(request, 'index', context_infos, is_index=True)


def show_search(request, keyword, page_num):
    # format the keyword, remove unusable char.
    keyword = keyword.replace('/', '').strip()
    start_index = _get_start_index(page_num)

    article_infos = blog_db.search_articles(keyword, start_index=start_index, count=settings.LIST_PER_PAGE,
                                            has_login=(not request.user.is_anonymous()), with_total=True)

    context_infos = {
        'page_title': keyword,
        'articles': _process_articles(article_infos['results']),
    }
    context_infos.update(_get_pagination_infos(article_infos, page_num))

    return _render_response(request, 'index', context_infos, is_index=True)


@cache_page(60 * 60 * 1)
def show_archive_page(request):
    articles = blog_db.get_articles({}, count=10000, fields={'_id': 0, 'id': 1, 'title': 1, 'publish_date': 1, 'slug': 1},
                                    has_login=(not request.user.is_anonymous()), with_total=True)

    from collections import defaultdict
    archives = defaultdict(dict)
    # format the data of archives for template
    for article in _process_articles(articles['results']):
        year, month = article['year'], article['month']
        archives[year].setdefault(month, []).append(article)

    # sort archives
    import operator
    sorted_archives = dict(sorted(archives.items(), key=operator.itemgetter(1), reverse=True))
    for year, all_months in sorted_archives.items():
        all_months.update({'month_list': sorted(all_months.keys(), reverse=True)})
        sorted_archives[year] = all_months

    context_infos = {
        'page_title': _('Archive'),
        'archives': sorted_archives,
        'years': sorted(sorted_archives.keys(), reverse=True),
        'total_num': articles['total'],
    }
    return _render_response(request, 'archive', context_infos)


@cache_page(60 * 60 * 1)
def show_about_page(request):
    return _render_response(request, 'about', {'page_title': _('About')})


@cache_page(60 * 60 * 1)
def show_friend_link_page(request):
    all_links = blog_db.get_all_links()
    friend_links = [link for link in all_links if link['type'] == LINK_TYPES.FRIEND_LINK]
    site_links = [link for link in all_links if link['type'] == LINK_TYPES.SITE_LINK]

    context_infos = {
        'id': 'friend',
        'page_title': ugettext('Friend Links'),
        'friend_links': friend_links,
        'site_links': site_links,
    }

    return _render_response(request, 'link', context_infos)
