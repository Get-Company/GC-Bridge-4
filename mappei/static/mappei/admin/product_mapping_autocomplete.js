'use strict';
{
    const selector = '.mappei-product-mapping-autocomplete';

    function buildResult($, item) {
        const $row = $('<span class="mappei-product-mapping-option"></span>');
        const imageUrl = item.image_url || '';

        if (imageUrl) {
            $('<img class="mappei-product-mapping-option__image" alt="">')
                .attr('src', imageUrl)
                .attr('loading', 'lazy')
                .appendTo($row);
        } else {
            $('<span class="mappei-product-mapping-option__placeholder" aria-hidden="true"></span>')
                .appendTo($row);
        }

        $('<span class="mappei-product-mapping-option__text"></span>')
            .text(item.text || '')
            .appendTo($row);

        return $row;
    }

    function initialize($, $elements) {
        $elements.each(function() {
            const element = this;
            const $element = $(element);

            if ($element.hasClass('select2-hidden-accessible')) {
                $element.select2('destroy');
            }

            $element.select2({
                ajax: {
                    cache: true,
                    delay: 250,
                    type: 'GET',
                    url: $element.attr('data-ajax--url'),
                    data: (params) => {
                        return {
                            term: params.term,
                            page: params.page,
                            app_label: element.dataset.appLabel,
                            model_name: element.dataset.modelName,
                            field_name: element.dataset.fieldName
                        };
                    }
                },
                allowClear: JSON.parse(element.dataset.allowClear || 'false'),
                placeholder: element.dataset.placeholder || '',
                templateResult: (item) => buildResult($, item),
                templateSelection: (item) => item.text || ''
            });
        });
    }

    document.addEventListener('DOMContentLoaded', () => {
        const $ = window.django && window.django.jQuery;
        if (!$) {
            return;
        }
        initialize($, $(selector).not('[name*=__prefix__]'));
    });

    document.addEventListener('formset:added', (event) => {
        const $ = window.django && window.django.jQuery;
        if (!$) {
            return;
        }
        initialize($, $(event.target).find(selector));
    });
}
