# -*- coding: utf-8 -*-
# Copyright (c) 2017, Libermatic and contributors
# For license information, please see license.txt

from __future__ import unicode_literals
import frappe
from frappe.utils import flt
from frappe.utils.data import getdate, today, date_diff, add_days, add_months
from erpnext.controllers.accounts_controller import AccountsController
from frappe.contacts.doctype.address.address import get_default_address
from erpnext.accounts.general_ledger import make_gl_entries
import math
from datetime import date

from microfinance.microfinance_loan.doctype.loan.loan_utils \
	import get_interval, get_periods

class Loan(AccountsController):
	def before_submit(self):
		self.disbursement_status = 'Sanctioned'
		self.recovery_status = 'Not Started'
	def update_from_application(self, application):
		'''Method used by Loan application to add to sanctioned amount'''
		amount = flt(application.amount)
		if amount < 0:
			frappe.throw('Cannot decrease principal')
		self.loan_principal += amount
		if not self.calculation_slab == application.calculation_slab:
			self.calculation_slab = application.calculation_slab
		if self.disbursement_status == 'Fully Disbursed':
			self.disbursement_status = 'Partially Disbursed'
		if self.stipulated_recovery_amount != application.stipulated_recovery_amount:
			self.stipulated_recovery_amount = application.stipulated_recovery_amount
		self.save()

	def get_gl_dict(self, args):
		gl_dict = frappe._dict({
				'against_voucher_type': 'Loan',
				'against_voucher': self.name
			})
		gl_dict.update(args)
		return super(Loan, self).get_gl_dict(gl_dict)

	def make_interest(self, posting_date, cancel=0, adv_adj=0):
		periods = get_billing_periods(self.name, posting_date, 1)
		if len(periods) != 1:
			return None
		amount = periods[0].get('interest')
		if amount:
			billing_period = periods[0].get('as_text')
			self.posting_date = posting_date
			gl_entries = [
				self.get_gl_dict({
						'account': self.interest_receivable_account,
						'debit': amount,
						'party_type': 'Customer',
						'party': self.customer,
						'against': self.interest_income_account,
						'period': billing_period,
					}),
				self.get_gl_dict({
						'account': self.interest_income_account,
						'credit': amount,
						'against': self.customer,
						'cost_center': frappe.db.get_value('Loan Settings', None, 'cost_center'),
						'remarks': 'Interest for period: {}'.format(billing_period),
					})
			]
			make_gl_entries(gl_entries, cancel=cancel, adv_adj=adv_adj)

	def convert_interest_to_principal(self, posting_date, cancel=0, adv_adj=0):
		periods = get_billing_periods(self.name, add_days(posting_date, -1), 1)
		if len(periods) != 1:
			return None
		amount = periods[0].get('interest')
		late_amount = amount * self.rate_of_late_charges / 100
		if amount:
			billing_period = periods[0].get('as_text')
			self.posting_date = posting_date
			gl_entries = [
				self.get_gl_dict({
						'account': self.interest_receivable_account,
						'credit': amount,
						'party_type': 'Customer',
						'party': self.customer,
						'against': self.loan_account,
						'period': billing_period,
					}),
				self.get_gl_dict({
						'account': self.loan_account,
						'debit': amount,
						'against': self.interest_receivable_account,
						'remarks': 'Converted to principal for: {}'.format(billing_period),
					})
			]
			if self.rate_of_late_charges:
				late_amount = amount * self.rate_of_late_charges / 100
				gl_entries.append(
					self.get_gl_dict({
							'account': self.interest_income_account,
							'credit': late_amount,
							'against': self.customer,
							'cost_center': frappe.db.get_value('Loan Settings', None, 'cost_center'),
							'remarks': 'Late charges for period: {}'.format(billing_period),
						})
					)
				gl_entries.append(
					self.get_gl_dict({
							'account': self.loan_account,
							'debit': late_amount,
							'against': self.interest_receivable_account,
							'remarks': 'Converted to principal for: {}'.format(billing_period),
						})
					)
			make_gl_entries(gl_entries, cancel=cancel, adv_adj=adv_adj)

@frappe.whitelist()
def get_undisbursed_principal(loan=None):
	'''Gets undisbursed principal'''
	if not loan:
		return None
	loan_doc = frappe.get_value(
			'Loan',
			loan,
			['loan_principal', 'loan_account'],
			as_dict=True
		)
	conds = [
			"account = '{}'".format(loan_doc.get('loan_account')),
			"voucher_type = 'Disbursement'",
			"against_voucher_type = 'Loan'",
			"against_voucher = '{}'".format(loan)
		]
	disbursed_principal = frappe.db.sql("""
			SELECT sum(debit)
			FROM `tabGL Entry`
			WHERE {}
		""".format(" AND ".join(conds)))[0][0] or 0
	return flt(loan_doc.get('loan_principal')) - disbursed_principal

@frappe.whitelist()
def get_outstanding_principal(loan, posting_date=None):
	'''Get outstanding principal'''
	loan_account = frappe.get_value('Loan', loan, 'loan_account')
	cond = [
			"account = '{}'".format(loan_account),
			"against_voucher_type = 'Loan'",
			"against_voucher = '{}'".format(loan),
		]
	if posting_date:
		if not isinstance(posting_date, date):
			posting_date = getdate(posting_date)
		cond.append("posting_date <= '{}'".format(posting_date))
	principal = frappe.db.sql("""
			SELECT sum(debit) - sum(credit)
			FROM `tabGL Entry`
			WHERE {}
		""".format(" AND ".join(cond)))[0][0] or 0
	return principal

@frappe.whitelist()
def get_recovered_principal(loan):
	'''Get recovered principal'''
	loan_account = frappe.get_value('Loan', loan, 'loan_account')

	conds = [
			"account = '{}'".format(loan_account),
			"against_voucher_type = 'Loan'",
			"against_voucher = '{}'".format(loan)
		]
	recovered = frappe.db.sql("""
			SELECT sum(credit) - sum(debit)
			FROM `tabGL Entry`
			WHERE voucher_type = 'Recovery' AND {}
		""".format(" AND ".join(conds)))[0][0] or 0
	unrecorded = frappe.db.sql("""
			SELECT sum(credit)
			FROM `tabGL Entry`
			WHERE voucher_type = 'Disbursement' AND {}
		""".format(" AND ".join(conds)))[0][0] or 0
	return recovered + unrecorded

def get_wrote_off_principal(loan):
	'''Wrote off amount'''
	company = frappe.get_value('Loan', loan, 'company')

	conds = [
			"account = '{}'".format(frappe.get_value('Company', company, 'write_off_account')),
			"against_voucher_type = 'Loan'",
			"against_voucher = '{}'".format(loan)
		]

	wrote_off = frappe.db.sql("""
			SELECT sum(debit - credit)
			FROM `tabGL Entry`
			where {}
		""".format(" AND ".join(conds)))[0][0] or 0
	return flt(wrote_off)

def get_interest(loan=None, start_date=today(), end_date=today()):
	'''Get interest amount'''
	if not loan:
		return None
	owed_amount = 0

	principal = get_outstanding_principal(loan, end_date)
	rate, slab = frappe.get_value('Loan', loan, ['rate_of_interest', 'calculation_slab'])
	if slab:
		principal = math.ceil(principal / slab) * slab
		owed_amount = principal * rate / 100.0

	period = '{} - {}'.format(start_date, end_date)
	interest_receivable_account = frappe.get_value(
			'Loan',
			loan,
			'interest_receivable_account'
		)

	conds = [
			"account = '{}'".format(interest_receivable_account),
			"period = '{}'".format(period),
			"against_voucher_type = 'Loan'",
			"against_voucher = '{}'".format(loan),
		]

	paid_amount = frappe.db.sql("""
			SELECT
				sum(credit) as paid
			FROM `tabGL Entry`
			WHERE {}
		""".format(" AND ".join(conds)))[0][0] or 0

	amount = owed_amount - paid_amount

	return amount if amount > 0 else 0

@frappe.whitelist()
def get_billing_periods(loan=None, interval_date=today(), no_of_periods=5):
	'''Returns start and end date of a period along with interest of the period'''
	billing_date, posting_date = frappe.get_value(
			'Loan',
			loan,
			['billing_date', 'posting_date']
		)
	intervals = get_periods(billing_date.day, interval_date, no_of_periods)

	def check_for_posting_date_and_get_interest(interval):
		if date_diff(interval.get('start_date'), posting_date) < 0:
			interval.update({
					'start_date': posting_date,
					'as_text': '{} - {}'.format(posting_date, interval.get('end_date'))
				})
		interval.update({
				'interest': get_interest(
						loan,
						interval.get('start_date'),
						interval.get('end_date')
					)
			})
		return interval

	periods = map(
			check_for_posting_date_and_get_interest,
			filter(
					lambda x: date_diff(x.get('end_date'), posting_date) > 0,
					intervals
				)
		)

	return periods

@frappe.whitelist()
def get_customer_address(customer=None):
	'''Returns formatted address of Customer'''
	if not customer:
		return None
	address = frappe.get_value(
			'Address',
			get_default_address('Customer', customer),
			['address_line1', 'address_line2', 'city', 'county', 'state', 'pincode'],
			as_dict=True
		) or {}
	state = ' - '.join(filter(lambda x: not not x, [
			address.get('state'),
			address.get('pincode'),
		]))
	return ', '.join(filter(lambda x: not not x, [
			address.get('address_line1'),
			address.get('address_line2'),
			address.get('city'),
			address.get('county'),
			state,
		]))
