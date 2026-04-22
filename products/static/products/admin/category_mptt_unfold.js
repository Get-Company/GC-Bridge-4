/* global django */

django.jQuery(function ($) {
  const resultList = $("#result_list")
  const contextElement = document.getElementById("category-mptt-unfold-context")
  const csrfToken = $("input[type=hidden][name=csrfmiddlewaretoken]").val()

  if (!resultList.length || !contextElement || !csrfToken) {
    return
  }

  const context = JSON.parse(contextElement.getAttribute("data-context") || "{}")
  const treeStructure = context.treeStructure || {}
  const collapsedNodes = []

  function rowBodies() {
    return resultList.children("tbody").has(".tree-node")
  }

  function visibleRowBodies() {
    return rowBodies().filter(":visible")
  }

  function treeNode(pk) {
    return $('.tree-node[data-pk="' + pk + '"]')
  }

  function rowBodyForNode(pk) {
    return treeNode(pk).closest("tbody")
  }

  function rowLevel(rowBody) {
    return Number(rowBody.find(".tree-node").first().data("level") || 0)
  }

  function nodePk(rowBody) {
    return rowBody.find(".tree-node").first().data("pk")
  }

  function isExpandedNode(id) {
    return collapsedNodes.indexOf(id) === -1
  }

  function markNodeAsExpanded(id) {
    const index = collapsedNodes.indexOf(id)
    if (index >= 0) {
      collapsedNodes.splice(index, 1)
    }
  }

  function markNodeAsCollapsed(id) {
    if (isExpandedNode(id)) {
      collapsedNodes.push(id)
    }
  }

  function storeCollapsedNodes() {
    if (window.localStorage) {
      window.localStorage.setItem(context.storageName, JSON.stringify(collapsedNodes))
    }
  }

  function retrieveCollapsedNodes() {
    if (!window.localStorage) {
      return []
    }
    try {
      return JSON.parse(window.localStorage.getItem(context.storageName)) || []
    } catch (_error) {
      return []
    }
  }

  function toggleDescendants(id, show) {
    const children = treeStructure[id] || []
    children.forEach(function (childId) {
      const childRow = rowBodyForNode(childId)
      if (show) {
        childRow.show()
        if (isExpandedNode(childId)) {
          toggleDescendants(childId, true)
        }
      } else {
        childRow.hide()
        toggleDescendants(childId, false)
      }
    })
  }

  function expandOrCollapseNode(node) {
    if (!node.hasClass("children")) {
      return
    }

    const itemId = node.data("pk")
    if (!isExpandedNode(itemId)) {
      node.removeClass("closed")
      markNodeAsExpanded(itemId)
      toggleDescendants(itemId, true)
    } else {
      node.addClass("closed")
      markNodeAsCollapsed(itemId)
      toggleDescendants(itemId, false)
    }
    storeCollapsedNodes()
  }

  function resetTreeUi() {
    rowBodies().show()
    rowBodies().find("tr").show()
    rowBodies().each(function (_index, element) {
      const marker = $(element).find(".tree-node").first()
      const pk = marker.data("pk")
      marker.toggleClass("children", Boolean(treeStructure[pk]))
      marker.removeClass("closed")
    })

    collapsedNodes.splice(0, collapsedNodes.length)
    retrieveCollapsedNodes().forEach(function (pk) {
      collapsedNodes.push(pk)
      treeNode(pk).addClass("closed")
      toggleDescendants(pk, false)
    })

    if (!retrieveCollapsedNodes().length && !context.expandTreeByDefault) {
      rowBodies().each(function (_index, element) {
        const marker = $(element).find(".tree-node.children").first()
        if (marker.length) {
          const pk = marker.data("pk")
          marker.addClass("closed")
          markNodeAsCollapsed(pk)
          toggleDescendants(pk, false)
        }
      })
      storeCollapsedNodes()
    }
  }

  function moveNode(cutItem, pastedOn, position) {
    $.ajax({
      complete: function () {
        window.location.reload()
      },
      data: {
        cmd: "move_node",
        position: position,
        cut_item: cutItem,
        pasted_on: pastedOn,
      },
      headers: {
        "X-CSRFToken": csrfToken,
      },
      method: "POST",
    })
  }

  function dragLineLeft(targetBody, targetLoc) {
    const titleCell = targetBody.find(".field-indented_title").first()
    const baseOffset = (titleCell.offset() || targetBody.offset()).left
    return baseOffset + rowLevel(targetBody) * context.levelIndent + (targetLoc === "child" ? context.levelIndent : 0) + 8
  }

  function bindDragHandle() {
    $(".drag-handle").off("mousedown").on("mousedown", function (event) {
      event.preventDefault()

      const originalBody = $(event.target).closest("tbody")
      const rowHeight = originalBody.outerHeight()
      const resultListWidth = resultList.width()
      const moveTo = {}

      $("body")
        .addClass("dragging")
        .on("mousemove.categoryMptt", function (moveEvent) {
          if (!$("#ghost").length) {
            $('<div id="ghost"></div>').appendTo("body")
          }

          $("#ghost")
            .html(originalBody.find("tr").first().html())
            .css({
              left: moveEvent.pageX - 30,
              opacity: 0.92,
              position: "absolute",
              top: moveEvent.pageY,
              width: Math.min(720, resultListWidth),
            })

          if (!$("#drag-line").length) {
            $("body").append('<div id="drag-line"><span></span></div>')
          }

          visibleRowBodies().each(function (_index, element) {
            const targetBody = $(element)
            const top = targetBody.offset().top
            const height = targetBody.outerHeight() || rowHeight

            if (moveEvent.pageY < top || moveEvent.pageY >= top + height) {
              return true
            }

            let targetLoc = null
            if (moveEvent.pageY < top + height / 3) {
              targetLoc = "before"
            } else if (moveEvent.pageY < top + (height * 2) / 3) {
              const next = targetBody.nextAll("tbody:visible").first()
              if (!next.length || rowLevel(next) <= rowLevel(targetBody)) {
                targetLoc = "child"
              }
            } else {
              const next = targetBody.nextAll("tbody:visible").first()
              if (!next.length || rowLevel(next) <= rowLevel(targetBody)) {
                targetLoc = "after"
              }
            }

            if (!targetLoc) {
              return false
            }

            const left = dragLineLeft(targetBody, targetLoc)
            $("#drag-line")
              .css({
                left: left,
                top: top + (targetLoc === "before" ? 0 : height),
                width: Math.max(120, resultListWidth - left),
              })
              .find("span")
              .text(context.messages[targetLoc] || "")

            moveTo.relativeTo = targetBody
            moveTo.side = targetLoc
            return false
          })
        })
        .on("mouseup.categoryMptt", function () {
          $("#drag-line").remove()
          $("#ghost").remove()
          $("body").removeClass("dragging").off(".categoryMptt")

          if (!moveTo.relativeTo) {
            return
          }

          const cutItem = nodePk(originalBody)
          const pastedOn = nodePk(moveTo.relativeTo)
          if (!cutItem || !pastedOn || cutItem === pastedOn) {
            return
          }

          const next = moveTo.relativeTo.nextAll("tbody:visible").first()
          const isParent = next.length && rowLevel(next) > rowLevel(moveTo.relativeTo)
          let position = "right"
          if (moveTo.side === "child" && !isParent) {
            position = "last-child"
          } else if (moveTo.side === "before") {
            position = "left"
          }

          moveNode(cutItem, pastedOn, position)
        })
    })
  }

  $(".tree-node").off("click").on("click", function (event) {
    event.preventDefault()
    event.stopPropagation()
    expandOrCollapseNode($(this))
  })

  resetTreeUi()
  bindDragHandle()
})
