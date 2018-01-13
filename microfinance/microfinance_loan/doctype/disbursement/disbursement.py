# -*- coding: utf-8 -*-
# Copyright (c) 2017, Libermatic and contributors
# For license information, please see license.txt

from __future__ import unicode_literals
import frappe
from frappe import _
from erpnext.accounts.general_ledger import make_gl_entries
from erpnext.controllers.accounts_controller import AccountsController
from frappe.utils.data import fmt_money

from microfinance.microfinance_loan.doctype.loan.loan import get_undisbursed_principal

class Disbursement(AccountsController):
	def validate(self):
		if self.amount > get_undisbursed_principal(self.loan):
			frappe.throw(_("Disbursed amount cannot exceed the sanctioned amount"))
		if self.recovered_amount >= self.amount:
			frappe.throw(_("Recovered amount cannot be equal to or exceed the disbursed amount"))

	def on_submit(self):
		self.make_gl_entries()
		self.update_loan_status()

	def on_cancel(self):
		self.make_gl_entries(cancel=True)
		self.update_loan_status()

	def make_gl_entries(self, cancel=0, adv_adj=0):
		gl_entries = self.add_loan_gl_entries()
		make_gl_entries(gl_entries, cancel=cancel, adv_adj=adv_adj)
		if len(self.loan_charges) > 0:
			gl_entries = self.add_loan_charges_entries()
			make_gl_entries(gl_entries, cancel=cancel, adv_adj=adv_adj, merge_entries=False)

	def add_loan_gl_entries(self):
		gl_entries = [
			self.get_gl_dict({
					'account': self.loan_account,
					'debit': self.amount,
					'against_voucher_type': 'Loan',
					'against_voucher': self.loan
				}),
			self.get_gl_dict({
					'account': self.payment_account,
					'credit': self.amount,
					'against': self.customer,
					'against_voucher_type': 'Loan',
					'against_voucher': self.loan
				})
		]
		return gl_entries

	def add_loan_charges_entries(self):
		gl_entries = []
		total = 0
		cost_center = frappe.db.get_value('Loan Settings', None, 'cost_center')
		for row in self.loan_charges:
			total += row.charge_amount
			gl_entries.append(
					self.get_gl_dict({
							'account': row.charge_account,
							'credit': row.charge_amount,
							'cost_center': cost_center,
							'against_voucher_type': 'Loan',
							'against_voucher': self.loan,
							'remarks': row.charge
						})
				)
		gl_entries.append(
				self.get_gl_dict({
						'account': self.payment_account,
						'debit': total,
						'against': self.customer,
						'against_voucher_type': 'Loan',
						'against_voucher': self.loan
					})
			)
		return gl_entries

	def update_loan_status(self):
		'''Method to update disbursement_status of Loan'''
		loan_principal, disbursement_status = frappe.get_value(
				'Loan',
				self.loan,
				['loan_principal', 'disbursement_status']
			)
		undisbursed_principal = get_undisbursed_principal(self.loan)
		loan = frappe.get_doc('Loan', self.loan)
		if undisbursed_principal <= loan_principal:
			if undisbursed_principal == loan_principal and disbursement_status != 'Sanctioned':
				loan.disbursement_status = 'Sanctioned'
			elif undisbursed_principal > 0 and disbursement_status != 'Partially Disbursed':
				loan.disbursement_status = 'Partially Disbursed'
			else:
				loan.disbursement_status = 'Fully Disbursed'
			return loan.save()
		return loan.name
