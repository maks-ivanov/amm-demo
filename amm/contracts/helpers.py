from pyteal import *

from amm.contracts.config import (
    SCALING_FACTOR,
    POOL_TOKENS_OUTSTANDING_KEY,
    POOL_TOKEN_KEY,
    AMP_FACTOR,
    D_KEY,
)


@Subroutine(TealType.uint64)
def validateTokenReceived(
    transaction_index: TealType.uint64, token_key: TealType.bytes
) -> Expr:
    return And(
        Gtxn[transaction_index].type_enum() == TxnType.AssetTransfer,
        Gtxn[transaction_index].sender() == Txn.sender(),
        Gtxn[transaction_index].asset_receiver()
        == Global.current_application_address(),
        Gtxn[transaction_index].xfer_asset() == App.globalGet(token_key),
        Gtxn[transaction_index].asset_amount() > Int(0),
    )


@Subroutine(TealType.uint64)
def xMulYDivZ(x, y, z) -> Expr:
    return WideRatio([x, y, SCALING_FACTOR], [z, SCALING_FACTOR])


@Subroutine(TealType.none)
def sendToken(
    token_key: TealType.bytes, receiver: TealType.bytes, amount: TealType.uint64
) -> Expr:
    return Seq(
        InnerTxnBuilder.Begin(),
        InnerTxnBuilder.SetFields(
            {
                TxnField.type_enum: TxnType.AssetTransfer,
                TxnField.xfer_asset: App.globalGet(token_key),
                TxnField.asset_receiver: receiver,
                TxnField.asset_amount: amount,
            }
        ),
        InnerTxnBuilder.Submit(),
    )


@Subroutine(TealType.none)
def createPoolToken(pool_token_amount: TealType.uint64) -> Expr:
    return Seq(
        InnerTxnBuilder.Begin(),
        InnerTxnBuilder.SetFields(
            {
                TxnField.type_enum: TxnType.AssetConfig,
                TxnField.config_asset_total: pool_token_amount,
                TxnField.config_asset_default_frozen: Int(0),
                TxnField.config_asset_decimals: Int(0),
                TxnField.config_asset_reserve: Global.current_application_address(),
            }
        ),
        InnerTxnBuilder.Submit(),
        App.globalPut(POOL_TOKEN_KEY, InnerTxn.created_asset_id()),
        App.globalPut(POOL_TOKENS_OUTSTANDING_KEY, Int(0)),
    )


@Subroutine(TealType.none)
def optIn(token_key: TealType.bytes) -> Expr:
    return sendToken(token_key, Global.current_application_address(), Int(0))


@Subroutine(TealType.none)
def returnRemainder(
    token_key: TealType.bytes,
    received_amount: TealType.uint64,
    to_keep_amount: TealType.uint64,
) -> Expr:
    remainder = received_amount - to_keep_amount
    return Seq(
        If(remainder > Int(0)).Then(
            sendToken(
                token_key,
                Txn.sender(),
                remainder,
            )
        ),
    )


@Subroutine(TealType.uint64)
def tryTakeAdjustedAmounts(
    to_keep_token_txn_amt: TealType.uint64,
    to_keep_token_before_txn_amt: TealType.uint64,
    other_token_key: TealType.bytes,
    other_token_txn_amt: TealType.uint64,
    other_token_before_txn_amt: TealType.uint64,
) -> Expr:
    """
    Given supplied token amounts, try to keep all of one token and the corresponding amount of other token
    as determined by market price before transaction. If corresponding amount is less than supplied, send the remainder back.
    If successful, mint and sent pool tokens in proportion to new liquidity over old liquidity.
    """
    other_corresponding_amount = ScratchVar(TealType.uint64)
    D0 = App.globalGet(D_KEY)
    new_keep_token_balance = to_keep_token_txn_amt + to_keep_token_before_txn_amt
    new_other_token_balance = (
        other_token_before_txn_amt + other_corresponding_amount.load()
    )
    D1 = getD(new_keep_token_balance, new_other_token_balance, AMP_FACTOR)

    mint_amount = xMulYDivZ(
        App.globalGet(POOL_TOKENS_OUTSTANDING_KEY),
        D1 - D0,
        D0,
    )
    # TODO adjust for fees

    return Seq(
        other_corresponding_amount.store(
            xMulYDivZ(
                to_keep_token_txn_amt,
                other_token_before_txn_amt,
                to_keep_token_before_txn_amt,
            )
        ),
        If(
            And(
                other_corresponding_amount.load() > Int(0),
                other_token_txn_amt >= other_corresponding_amount.load(),
            )
        ).Then(
            Seq(
                returnRemainder(
                    other_token_key,
                    other_token_txn_amt,
                    other_corresponding_amount.load(),
                ),
                mintAndSendPoolToken(Txn.sender(), mint_amount),
                Return(Int(1)),
            )
        ),
        Return(Int(0)),
    )


@Subroutine(TealType.none)
def withdrawGivenPoolToken(
    receiver: TealType.bytes,
    to_withdraw_token_key: TealType.bytes,
    pool_token_amount: TealType.uint64,
    pool_tokens_outstanding: TealType.uint64,
) -> Expr:
    token_holding = AssetHolding.balance(
        Global.current_application_address(), App.globalGet(to_withdraw_token_key)
    )
    return Seq(
        token_holding,
        If(
            And(
                pool_tokens_outstanding > Int(0),
                pool_token_amount > Int(0),
                token_holding.hasValue(),
                token_holding.value() > Int(0),
            )
        ).Then(
            Seq(
                Assert(
                    xMulYDivZ(
                        token_holding.value(),
                        pool_token_amount,
                        pool_tokens_outstanding,
                    )
                    > Int(0)
                ),
                sendToken(
                    to_withdraw_token_key,
                    receiver,
                    xMulYDivZ(
                        token_holding.value(),
                        pool_token_amount,
                        pool_tokens_outstanding,
                    ),
                ),
            )
        ),
    )


@Subroutine(TealType.uint64)
def assessFee(amount: TealType.uint64, fee_bps: TealType.uint64):
    fee_num = Int(10000) - fee_bps
    fee_denom = Int(10000)
    return xMulYDivZ(amount, fee_num, fee_denom)


@Subroutine(TealType.uint64)
def computeOtherTokenOutputPerGivenTokenInput(
    input_amount: TealType.uint64,
    previous_given_token_amount: TealType.uint64,
    previous_other_token_amount: TealType.uint64,
    fee_bps: TealType.uint64,
):
    k = previous_other_token_amount * previous_given_token_amount
    amount_sub_fee = assessFee(input_amount, fee_bps)
    to_send = previous_other_token_amount - k / (
        previous_given_token_amount + amount_sub_fee
    )
    return to_send


@Subroutine(TealType.none)
def mintAndSendPoolToken(receiver: TealType.bytes, amount: TealType.uint64) -> Expr:
    return Seq(
        sendToken(POOL_TOKEN_KEY, receiver, amount),
        App.globalPut(
            POOL_TOKENS_OUTSTANDING_KEY,
            App.globalGet(POOL_TOKENS_OUTSTANDING_KEY) + amount,
        ),
    )


@Subroutine(TealType.uint64)
def getD(
    tokenA_amount: TealType.uint64,
    tokenB_amount: TealType.uint64,
    amplification_param: TealType.uint64,
):
    """
    WARNING: this is likely not safe from overflow
    StableSwap two tokens implementation
    D invariant calculation in non-overflowing integer operations
    iteratively
    A * sum(x_i) * n**n + D = A * D * n**n + D**(n+1) / (n**n * prod(x_i))
    Converging solution:
    D[j+1] = (A * n**n * sum(x_i) - D[j]**(n+1) / (n**n prod(x_i))) / (A * n**n - 1)
    """
    n_coins = Int(2)
    S = tokenA_amount + tokenB_amount
    D = ScratchVar(TealType.uint64)
    D_P = ScratchVar(TealType.uint64)

    Ann = amplification_param * Exp(n_coins, n_coins)  # TODO
    i = ScratchVar(TealType.uint64)

    Dprev = ScratchVar(TealType.uint64)
    # TODO fee adjustment
    calc = Seq(
        If(S == Int(0)).Then(Return(S)),
        D.store(S),
        For(i.store(Int(0)), i.load() < Int(255), i.store(i.load() + Int(1))).Do(
            Seq(
                D_P.store(
                    WideRatio(
                        [
                            D.load(),
                            D.load(),
                            D.load(),
                        ],  # D ** (n+1); Exp can and does overflow, so here we are.
                        [Exp(n_coins, n_coins), tokenA_amount, tokenB_amount],
                    )
                ),
                Dprev.store(D.load()),
                D.store(
                    WideRatio(
                        [(Ann * S / SCALING_FACTOR + D_P.load() * n_coins), D.load()],
                        [
                            (Ann - SCALING_FACTOR) * D.load() / SCALING_FACTOR
                            + (n_coins + Int(1)) * D_P.load()
                        ],
                    )
                ),
                If(D.load() > Dprev.load())
                .Then(If(D.load() - Dprev.load() <= Int(1)).Then(Return(D.load())))
                .Else(If(Dprev.load() - D.load() <= Int(1)).Then(Return(D.load()))),
            )
        ),
        Assert(i.load() < Int(255)),  # did not converge, throw error
        Return(Int(0)),  # unreachable code
    )

    return calc


@Subroutine(TealType.uint64)
def computeOtherTokenOutputStableSwap(
    given_token_total: TealType.uint64,
    previous_other_token_total: TealType.uint64,
    fee_bps: TealType.uint64,
    amplification_param,
):
    n_tokens = Int(2)
    D = App.globalGet(D_KEY)
    Ann = amplification_param * Exp(n_tokens, n_tokens)
    S = given_token_total
    b = S + D * SCALING_FACTOR / Ann
    c = WideRatio(
        [D, D, D, SCALING_FACTOR],
        [given_token_total, Ann, Exp(n_tokens, n_tokens)],
    )


    new_other_token_total_estimate = ScratchVar(TealType.uint64)

    new_other_token_total_estimate_prev = ScratchVar(TealType.uint64)
    i = ScratchVar(TealType.uint64)
    ret = Return(
        assessFee(
            previous_other_token_total - new_other_token_total_estimate.load(), fee_bps
        )
    )

    calc = Seq(
        new_other_token_total_estimate.store(D),
        For(i.store(Int(0)), i.load() < Int(255), i.store(i.load() + Int(1))).Do(
            Seq(
                new_other_token_total_estimate_prev.store(
                    new_other_token_total_estimate.load()
                ),
                new_other_token_total_estimate.store(
                    (
                        new_other_token_total_estimate.load()
                        * new_other_token_total_estimate.load()
                        + c
                    )
                    / (Int(2) * new_other_token_total_estimate.load() + b - D)
                ),
                If(
                    new_other_token_total_estimate.load()
                    > new_other_token_total_estimate_prev.load()
                )
                .Then(
                    If(
                        new_other_token_total_estimate.load()
                        - new_other_token_total_estimate_prev.load()
                        <= Int(1)
                    ).Then(ret)
                )
                .Else(
                    If(
                        new_other_token_total_estimate_prev.load()
                        - new_other_token_total_estimate.load()
                        <= Int(1)
                    ).Then(ret)
                ),
            )
        ),
        Assert(i.load() < Int(255)),  # did not converge, throw error
        Return(Int(0)),  # unreachable
    )

    return calc
