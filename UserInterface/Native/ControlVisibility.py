"""Read-only geometry and visibility evidence for Qt controls.

The helper describes a control in the coordinate space of an explicit root
widget.  It intentionally performs no event processing, widget mutation or
model access: callers may use it from a non-blocking GUI verifier.
"""

from __future__ import annotations

from PyQt5.QtCore import QPoint, QRect
from PyQt5.QtGui import QRegion
from PyQt5.QtWidgets import QWidget

__all__ = ['control_visibility']


def _widget_label(widget: QWidget) -> str:
    object_name = widget.objectName().strip()
    class_name = type(widget).__name__
    return f'{class_name}#{object_name}' if object_name else class_name


def _contains_control(candidate: QWidget | None, control: QWidget) -> bool:
    current = candidate
    while current is not None:
        if current is control:
            return True
        current = current.parentWidget()
    return False


def _region_covers(region: QRegion, rect: QRect) -> bool:
    """Require every pixel; QRegion.contains(QRect) can accept an overlap."""

    return not rect.isEmpty() and QRegion(rect).subtracted(region).isEmpty()


def control_visibility(root, control) -> dict:
    """Return JSON-safe visibility evidence for ``control`` relative to ``root``.

    ``root`` must be the control itself or one of its ancestors.  A control is
    only reported fully visible when its complete rectangle is inside every
    ancestor, its visible region is unmasked and the root hit-tests to it (or
    one of its descendants).
    """

    if not isinstance(root, QWidget) or not isinstance(control, QWidget):
        raise ValueError('root and control must be QWidget instances')
    if control is not root and not root.isAncestorOf(control):
        raise ValueError('control is not a descendant of root')

    top_left = control.mapTo(root, QPoint(0, 0))
    control_rect = QRect(top_left, control.size())
    rect_values = [int(value) for value in control_rect.getRect()]

    visible = bool(control.isVisible())
    enabled = bool(control.isEnabled())
    nonempty = control_rect.width() > 0 and control_rect.height() > 0

    clipped_by: list[str] = []
    if control is not root:
        ancestor = control.parentWidget()
        while ancestor is not None:
            mapped_rect = QRect(control.mapTo(ancestor, QPoint(0, 0)), control.size())
            ancestor_mask = ancestor.mask()
            if (not ancestor.rect().contains(mapped_rect)
                    or (not ancestor_mask.isEmpty()
                        and not _region_covers(ancestor_mask, mapped_rect))):
                label = _widget_label(ancestor)
                if label not in clipped_by:
                    clipped_by.append(label)
            if ancestor is root:
                break
            ancestor = ancestor.parentWidget()

    # An ancestor's visibleRegion can exclude its opaque descendants (notably
    # scroll viewports/content). Those descendants are this control's own
    # drawing surface, not occluders. Use ancestor bounds/masks above and the
    # control's visible region for sibling/paint occlusion instead.
    visible_region = control.visibleRegion()
    region_covers_control = bool(
        _region_covers(visible_region, control.rect())
    )
    if not region_covers_control:
        clipped_by.append(f'{_widget_label(control)}:visibleRegion')
    # Some Qt platform plugins report an unmasked visibleRegion even with an
    # explicit QWidget mask. Check mask geometry directly as well.
    own_mask = control.mask()
    if not own_mask.isEmpty() and not _region_covers(own_mask, control.rect()):
        clipped_by.append(f'{_widget_label(control)}:mask')

    hit_test = False
    if nonempty and visible:
        center = QPoint(control_rect.width() // 2, control_rect.height() // 2)
        mapped_center = control.mapTo(root, center)
        if control is root:
            hit_test = bool(root.rect().contains(mapped_center))
        else:
            hit_test = _contains_control(root.childAt(mapped_center), control)

    fully_visible = bool(
        nonempty
        and visible
        and not clipped_by
        and region_covers_control
        and hit_test
    )

    return {
        'rect': rect_values,
        'visible': visible,
        'enabled': enabled,
        'hit_test': bool(hit_test),
        'clipped_by': clipped_by,
        'fully_visible': fully_visible,
    }
