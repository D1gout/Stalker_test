#!/usr/bin/env python2
# -*- coding: utf-8 -*-

from __future__ import print_function
import sys
import io
import re
import os
import json
import collections
import datetime
import xml.etree.ElementTree as ET
from collections import deque

ITEM_NAMES = {}
PLAYER_NAMES = {}
INVENTORY_FILE = 'inventory_logs.txt'
MONEY_FILE = 'money_logs.txt'
COMBINED_FILE = 'combined_log.txt'
OUTPUT_FILE = 'output.txt'

def get_item_name(item_id):
    return ITEM_NAMES.get(item_id, u'Предмет %s' % item_id)

def get_player_name(player_id):
    return PLAYER_NAMES.get(player_id, u'Игрок %s' % player_id)

if sys.version_info[0] == 2:
    text_type = unicode
else:
    text_type = str

def toint(s):
    try:
        return int(s)
    except:
        return 0

TIMESTAMP_PATTERNS = [
    '%Y-%m-%d %H:%M:%S',
    '%y-%m-%d %H:%M:%S',
    '%Y-%m-%dT%H:%M:%S',
    '%y-%m-%dT%H:%M:%S',
]

BRACKET_RE = re.compile(r'^\s*\[([^\]]+)\]\s*$')


def parse_timestamp(s):
    if s is None:
        return None, None
    s = s.strip()

    m = BRACKET_RE.match(s)
    if m:
        s2 = m.group(1).strip()
    else:
        s2 = s

    if s2.isdigit() and len(s2) in (10, 13):
        ts_int = int(s2[:10])
        dt = datetime.datetime.utcfromtimestamp(ts_int)
        out = '[%s]' % dt.strftime('%y-%m-%d %H:%M:%S')
        return dt, out

    for fmt in TIMESTAMP_PATTERNS:
        try:
            dt = datetime.datetime.strptime(s2, fmt)
            out = '[%s]' % dt.strftime('%y-%m-%d %H:%M:%S')
            return dt, out
        except Exception:
            pass


class Player(object):
    def __init__(self, player_id):
        self.player_id = int(player_id)
        self.money = 0
        self.inventory = collections.defaultdict(int)
        self.first_ts = None
        self.last_ts = None

    def touch_ts(self, dt):
        if dt is None:
            return
        if self.first_ts is None or dt < self.first_ts:
            self.first_ts = dt
        if self.last_ts is None or dt > self.last_ts:
            self.last_ts = dt

    def add_item(self, item_id, amount):
        self.inventory[item_id] += amount

    def remove_item(self, item_id, amount):
        self.inventory[item_id] -= amount

    def add_money(self, amount):
        self.money += amount

INV_LINE_RE = re.compile(r'^(\s*\[[^\]]+\]|[^|]+)\s+([^|]+)\|\s*(\d+)\s*,\s*\((.*)\)\s*$')


def parse_inventory_line(raw):
    line = raw.strip()
    ts_part = ''
    rest = line
    if line.startswith('['):
        idx = line.find(']')
        if idx != -1:
            ts_part = line[:idx+1]
            rest = line[idx+1:].strip()
    else:
        m = re.match(r'^(\S+)\s+(.*)$', line)
        if m:
            ts_part = m.group(1)
            rest = m.group(2)
    parts = rest.split('|', 1)
    if len(parts) != 2:
        return None
    action_type = parts[0].strip()
    right = parts[1].strip()
    m = re.match(r'^(\d+)\s*,\s*\((.*)\)\s*$', right)
    if not m:
        return None
    player_id = m.group(1)
    pairs_s = m.group(2).strip()
    if pairs_s == '':
        pairs = []
    else:
        parts = [p.strip() for p in pairs_s.split(',')]
        nums = []
        for p in parts:
            p2 = re.sub(r'[^0-9\-]', '', p)
            if p2 == '':
                continue
            nums.append(p2)
        pairs = []
        i = 0
        while i+1 < len(nums):
            item_id = int(nums[i])
            amount = int(nums[i+1])
            pairs.append((item_id, amount))
            i += 2
    dt, out_ts = parse_timestamp(ts_part)
    return dt, out_ts, action_type, int(player_id), pairs


def parse_money_line(raw):
    line = raw.strip()
    parts = line.split('|')
    if len(parts) < 3:
        return None
    ts_part = parts[0].strip()
    player_part = parts[1].strip()
    right = '|'.join(parts[2:]).strip()
    m = re.match(r'^([^,\s]+)\s*,\s*([+-]?\d+)\s*,\s*(.*)$', right)
    if not m:
        m2 = re.match(r'^([^,\s]+)\s*,\s*([+-]?\d+)\s*$', right)
        if not m2:
            return None
        action_type = m2.group(1)
        amount = int(m2.group(2))
        reason = ''
    else:
        action_type = m.group(1)
        amount = int(m.group(2))
        reason = m.group(3).strip()
    dt, out_ts = parse_timestamp(ts_part)
    try:
        player_id = int(player_part)
    except:
        return None
    return dt, out_ts, action_type, player_id, amount, reason


def open_or_none(path):
    try:
        return io.open(path, 'r', encoding='utf-8', errors='ignore')
    except Exception:
        try:
            return open(path, 'r')
        except Exception:
            return None

def load_players(path):
    global PLAYER_NAMES
    try:
        with open(path, 'r') as f:
            data = json.load(f)

        players = data.get("players", [])
        for p in players:
            pid = p.get("id")
            name = p.get("name")
            if pid is not None and name:
                PLAYER_NAMES[int(pid)] = unicode(name)
    except:
        pass


def load_items(path):
    global ITEM_NAMES
    try:
        tree = ET.parse(path)
        root = tree.getroot()
        for item in root.findall('item'):
            iid_text = item.find('item_type_id')
            name_text = item.find('item_name')

            if iid_text is None or name_text is None:
                continue

            iid = int(iid_text.text.strip())
            item_name = unicode(name_text.text.strip())

            ITEM_NAMES[iid] = item_name
    except:
        pass


def merge_and_process(inv_path, money_path, combined_path, output_path):
    inv_f = open_or_none(inv_path)
    money_f = open_or_none(money_path)
    if inv_f is None or money_f is None:
        print('Error: could not open input files', file=sys.stderr)
        return

    out_f = io.open(combined_path, 'w', encoding='utf-8')

    players = {}
    item_occurrences = collections.Counter()

    first_items = []
    last_items = deque(maxlen=10)

    def next_inventory_line(filehandle):
        for raw in filehandle:
            raw = raw.rstrip('\n')
            if not raw.strip():
                continue
            parsed = parse_inventory_line(raw)
            if parsed is None:
                continue
            dt, out_ts, action_type, player_id, pairs = parsed
            yield dt, out_ts, 'inventory', action_type.strip(), player_id, pairs, raw
        return

    def next_money_line(filehandle):
        for raw in filehandle:
            raw = raw.rstrip('\n')
            if not raw.strip():
                continue
            parsed = parse_money_line(raw)
            if parsed is None:
                continue
            dt, out_ts, action_type, player_id, amount, reason = parsed
            yield dt, out_ts, 'money', action_type.strip(), player_id, amount, reason, raw
        return

    inv_iter = next_inventory_line(inv_f)
    money_iter = next_money_line(money_f)

    try:
        inv_cur = inv_iter.next()
    except StopIteration:
        inv_cur = None
    try:
        money_cur = money_iter.next()
    except StopIteration:
        money_cur = None

    total_lines = 0
    while inv_cur is not None or money_cur is not None:
        choose_inv = False
        if inv_cur is None:
            choose_inv = False
        elif money_cur is None:
            choose_inv = True
        else:
            inv_dt = inv_cur[0]
            money_dt = money_cur[0]
            if inv_dt is None and money_dt is None:
                choose_inv = True
            elif inv_dt is None:
                choose_inv = False
            elif money_dt is None:
                choose_inv = True
            else:
                if inv_dt < money_dt:
                    choose_inv = True
                elif inv_dt > money_dt:
                    choose_inv = False
                else:
                    choose_inv = True
        if choose_inv:
            dt, out_ts, typ, action_type, player_id, pairs, raw = inv_cur
            parts = []
            for (iid, amt) in pairs:
                parts.append('(%d, %d)' % (iid, amt))
            line = '%s %d | %s %s' % (out_ts if out_ts else '[00-00-00 00:00:00]', player_id, action_type, ' '.join(parts))
            out_f.write(line + u"\n")
            p = players.get(player_id)
            if p is None:
                p = Player(player_id)
                players[player_id] = p
            p.touch_ts(dt)
            for (iid, amt) in pairs:
                if action_type == 'ITEM_ADD':
                    p.add_item(iid, amt)
                else:
                    p.remove_item(iid, amt)
                item_occurrences[iid] += 1
                if len(first_items) < 10:
                    first_items.append((iid, dt))
                last_items.append((iid, dt))
            try:
                inv_cur = inv_iter.next()
            except StopIteration:
                inv_cur = None
        else:
            dt, out_ts, typ, action_type, player_id, amount, reason, raw = money_cur
            line = '%s %d | %s | %d | %s' % (out_ts if out_ts else '[00-00-00 00:00:00]', player_id, action_type, amount, reason)
            out_f.write(line + u"\n")
            p = players.get(player_id)
            if p is None:
                p = Player(player_id)
                players[player_id] = p
            p.touch_ts(dt)
            if action_type == 'MONEY_ADD':
                p.add_money(amount)
            else:
                p.add_money(-amount)
            try:
                money_cur = money_iter.next()
            except StopIteration:
                money_cur = None
        total_lines += 1
        if total_lines % 1000000 == 0:
            print('Processed', total_lines, 'lines...')

    out_f.close()
    inv_f.close()
    money_f.close()

    top_items = item_occurrences.most_common(10)

    players_list = list(players.values())
    players_list.sort(key=lambda x: (-x.money, x.player_id))
    top_players_money = players_list[:10]

    first10_items = first_items[:10]
    last10_items = list(last_items)

    item_total = collections.Counter()
    item_players_count = collections.Counter()
    for p in players.values():
        for iid, amt in p.inventory.items():
            if amt == 0:
                continue
            item_total[iid] += amt
            item_players_count[iid] += 1

    with io.open(output_path, 'w', encoding='utf-8') as outf:
        outf.write(u'Топ 10 предметов по количеству упоминаний в логах:\n')
        for iid, cnt in top_items:
            name = get_item_name(iid)
            outf.write(u'%s, %d\n' % (name, cnt))
        outf.write(u'\n')

        outf.write(u'Топ 10 игроков по количеству денег после обработки всех логов:\n')
        for p in top_players_money:
            name = get_player_name(p.player_id)
            first = p.first_ts.strftime('[%y-%m-%d %H:%M:%S]') if p.first_ts else '[00-00-00 00:00:00]'
            last = p.last_ts.strftime('[%y-%m-%d %H:%M:%S]') if p.last_ts else '[00-00-00 00:00:00]'
            outf.write(u'%s, %d, %s, %s\n' % (name, p.money, first, last))
        outf.write(u'\n')

        outf.write(u'Первые 10 предметов, упомянутые в логах (в порядке появления):\n')
        for iid, dt in first10_items:
            name = get_item_name(iid)
            dstr = dt.strftime('[%y-%m-%d %H:%M:%S]') if dt else '[00-00-00 00:00:00]'
            outf.write(u'%s, %s\n' % (name, dstr))
        outf.write(u'\n')

        outf.write(u'Последние 10 предметов, упомянутые в логах (в порядке появления):\n')
        for iid, dt in last10_items:
            name = get_item_name(iid)
            dstr = dt.strftime('[%y-%m-%d %H:%M:%S]') if dt else '[00-00-00 00:00:00]'
            outf.write(u'%s, %s\n' % (name, dstr))
        outf.write(u'\n')

    print('Done. Combined log written to %s, summary to %s' % (combined_path, output_path))

    print('\nInteractive mode: введите item_type_id (или q для выхода)')
    while True:
        try:
            sys.stdout.write('item_type_id> ')
            sys.stdout.flush()
            line = sys.stdin.readline()
            if not line:
                break
            line = line.strip()
            if line.lower() in ('q', 'quit', 'exit'):
                break
            if not line:
                continue
            try:
                qid = int(line)
            except:
                print('Введите числовой item_type_id')
                continue

            item_name = get_item_name(qid)

            # --- вычисляем на лету ---
            have_list = []
            total_count = 0
            for p in players.values():
                amt = p.inventory.get(qid, 0)
                if amt > 0:
                    have_list.append((amt, p.player_id))
                    total_count += amt

            players_count = len(have_list)
            have_list.sort(reverse=True)  # сортируем по количеству

            print(u'Название предмета: %s' % item_name)
            print('Общее количество в наличии в игре: %d' % total_count)
            print('Количество игроков, у которых есть предмет: %d' % players_count)
            print('Топ %d игроков по количеству предметов типа %d:' % (min(10, len(have_list)), qid))
            for amt, pid in have_list[:10]:
                pname = get_player_name(pid)
                print('%s, %d' % (pname, amt))

        except (KeyboardInterrupt, EOFError):
            break


if __name__ == '__main__':
    load_players("db.json")
    load_items("items.xml")
    merge_and_process(INVENTORY_FILE, MONEY_FILE, COMBINED_FILE, OUTPUT_FILE)
